# PULSIA Almacén — Documentación maestra del servidor

**Estado consolidado:** 28/08/2026  
**Versión funcional documentada:** v33.4 consolidada con todas las mejoras integradas en esta entrega  
**Objetivo:** documento único de referencia para mantenimiento humano y continuidad del proyecto en otro modelo de IA.

> Este documento sustituye todos los README parciales y notas `VERSION_*`. A partir de esta versión cualquier cambio debe documentarse aquí, no en documentos adicionales de cambios.

## 1. Descripción general

PULSIA Almacén es una aplicación web interna de inventario técnico basada en Django. Gestiona inventario dinámico, movimientos, reservas, préstamos, incidencias, producción, lotes de clientes, chat, seguridad, copias de seguridad, almacenamiento, impresión y tareas de administración del servidor.

En Linux se despliega normalmente en `/almacen`. Waitress ejecuta Django en `127.0.0.1:8080` y Caddy actúa como frontal HTTPS. SQLite es la BD por defecto en `/almacen/data/inventario.sqlite3`; PostgreSQL es opcional mediante `DATABASE_URL`.

## 2. Invariantes que no deben romperse

- El ID interno de inventario nunca se suplanta, edita o duplica.
- Todo campo dinámico distinto del ID debe aceptar contenido alfanumérico, aunque históricamente figure como número, fecha o booleano.
- `InventoryRecord.save()` debe sanear datos antes de escribir el JSON y evitar HTTP 500 por tipos Python no serializables.
- Una reserva real requiere objeto + destino/zona + SN de destino. Con datos parciales el objeto no debe quedar reservado.
- Producción, Reservas y Componentes sobrantes usan una única fuente de zonas: `ProductionZone`.
- Solo el Gestor/superuser puede crear, renombrar, ordenar, activar o desactivar zonas.
- Las IP de loopback `127.0.0.0/8` y `::1` no pueden bloquearse.
- Una actualización nunca debe copiar sobre producción la BD incluida en el paquete.
- El actualizador estructural protege el contenido de `InventoryTable` e `InventoryRecord` y revierte si detecta cambios no deseados.
- `.env`, `data/`, `backups/`, `logs/`, `certs/` y `.venv/` se preservan durante actualizaciones.
- Los cambios sensibles deben conservar trazabilidad.

## 3. Arquitectura

```text
Navegador/cliente
      │ HTTPS
      ▼
    Caddy
      │ reverse proxy
      ▼
Waitress 127.0.0.1:8080
      │
    Django
      │
 ┌────┴────────────┐
 ▼                 ▼
SQLite/PostgreSQL  Servicios auxiliares Linux
                   storage / backup / DHCP-DNS
```

| Componente | Función |
|---|---|
| Django 5.2 | Lógica web, permisos, modelos, formularios, migraciones y UI. |
| Waitress | Servidor WSGI ligado a loopback. |
| Caddy | TLS y proxy; único responsable de HTTP→HTTPS. |
| SQLite | BD por defecto, WAL y snapshots consistentes. |
| PostgreSQL | BD alternativa por `DATABASE_URL`. |
| storage-admin | Operaciones privilegiadas de almacenamiento mediante socket Unix. |
| continuous-backup | Protección y copias continuas en Linux. |

## 4. Estructura principal del repositorio

```text
almacen/
├── manage.py
├── config/                 settings, urls y WSGI
├── inventory/              aplicación Django principal
│   ├── models.py
│   ├── forms.py
│   ├── views.py
│   ├── urls.py
│   ├── middleware.py
│   ├── security.py
│   ├── services.py
│   ├── db_utils.py
│   ├── backup_scheduler.py
│   ├── external_mysql.py
│   ├── networking.py
│   ├── printing.py
│   ├── storage_admin.py
│   ├── migrations/
│   └── templates/
├── sistema/linux/ubuntu/
├── sistema/linux/debian/
├── sistema/common/
├── sistema/caddy/
├── cliente/
├── data/                   datos persistentes
├── requirements/
├── .env                    configuración local/secreta
└── DOCUMENTACION_MAESTRA_PULSIA_ALMACEN.md
```

## 5. Roles y permisos

| Rol | Alcance |
|---|---|
| Gestor | `superuser`. Máximos permisos; usuarios, zonas, seguridad, backups, estructura y acciones críticas. Exento de política horaria. |
| Administrador | `staff` no superuser. Gestión operativa y supervisión; no edita el catálogo maestro de zonas. |
| Usuario | Operación normal: inventario, reservas, préstamos, producción y comunicaciones permitidas. |
| Invitado | Acceso inicial limitado; puede solicitar ascenso y usar funciones expresamente habilitadas. |

Las cuentas auto-registradas nacen como Invitado. El Gestor puede promover o degradar roles. Las cuentas retiradas se archivan/desactivan en lugar de borrarse físicamente para conservar relaciones e históricos.

## 6. Inventario dinámico

El núcleo actual es `InventoryTable` + `InventoryField` + `InventoryRecord`; `RecordMovement` conserva trazabilidad. Cada tabla define nombre, patrón de ID y campos; cada objeto almacena su ID rígido y el resto de datos dinámicos en JSON.

### 6.1 Identificadores

`internal_id` es inmutable y no se toma del formulario al editar. La generación del siguiente ID debe estar en la misma transacción que el alta para no consumir números si falla el guardado.

### 6.2 Campos flexibles y corrección de los antiguos 500

Los campos no-ID se tratan como texto libre. `field_type` es metadato y no debe crear barreras `DecimalField`, `DateField` o booleanas en el formulario dinámico. Son válidos valores como `11.4V / 5200mAh`, `BAT-26/A`, `REV-A`, `N/A`, `4+4 GB` o fechas textuales. El modelo realiza un saneamiento final del JSON para convertir tipos no serializables y evitar errores 500.

### 6.3 SN, técnico y placas base

SN y técnico son campos reales cuando la tabla los define y no deben ocultarse/vaciarse en altas. Se sincronizan con `current_sn`/`current_technician` cuando aplica. Las placas base conservan lógica específica de disponibilidad; un estado `KO` implica no disponible y un SN existente debe mostrarse, nunca convertirse en «No disponible» por un fallo de mapeo.

## 7. Reservas

El flujo separa solicitud, aprobación y entrega física. Una solicitud o aprobación simple no equivale a entrega. La reserva válida requiere tres datos presentes: objeto, zona/destino y SN de destino. Con 0/3, 1/3 o 2/3 el objeto no debe quedar reservado. Los valores admiten alfanumérico; la restricción es de presencia, no de formato.

Las zonas de reserva se obtienen de `ProductionZone`.

## 8. Préstamos

`LoanItem`, `LoanRequest` y `Loan` gestionan material prestable, solicitudes, retirada, prestatario, devolución y trazabilidad. La interfaz integra búsqueda y solicitud.

## 9. Incidencias y guardado forzado

`Incident` centraliza duplicados de importación, errores y comunicaciones operativas. Un ID duplicado nunca sobrescribe automáticamente un registro existente: se genera una incidencia para decisión humana.

La resolución puede usar **Guardar de todos modos**: persiste valores alfanuméricos crudos saltando validaciones de formato, pero nunca permite alterar el ID existente ni crear un ID duplicado. El uso queda registrado en auditoría/movimientos/payload.

## 10. Componentes sobrantes

Los usuarios pueden comunicar componentes sobrantes indicando tipo, zona y estado. Se genera una incidencia pendiente hasta que se confirme la recogida. La zona se toma del catálogo único.

## 11. Catálogo único de zonas

`ProductionZone` sustituye las listas estáticas que existían en distintas pantallas. Es la única fuente para Producción, Reservas y Componentes sobrantes. Solo el Gestor puede añadir, renombrar, ordenar, activar o desactivar. El código de zona es estable aunque cambie el nombre y las zonas desactivadas siguen resolviendo históricos. La migración asociada es `0027_unified_production_zones.py`.

## 12. Producción / Pizarra

`ProductionEntry` registra usuario, fecha, hora, modelo, RAM, disco, procesador, zona de origen, zona de destino y cantidad. Origen y destino se eligen en cada anotación y quedan guardados históricamente.

- RAM sugerida: 4, 8, 16, 32, 64 GB; admite otro entero positivo.
- Disco sugerido: 128, 240, 256, 500, 512 GB; admite otro entero positivo.
- Procesadores: catálogo `ProductionProcessor`, ampliable por Gestor.
- Modelos: catálogo `ProductionModel`; retirados/excluidos en `ProductionModelExclusion`.
- Informes: filtros en pantalla y exportación Excel.

### 12.1 Importación de modelos desde MySQL

`ProductionModelMySQLSource` guarda host, puerto, BD y usuario. La contraseña se cifra con Fernet usando una clave derivada de `DJANGO_SECRET_KEY`. La consulta está fijada a `Manufacturer` y `Model` de `Units`; la interfaz no acepta SQL arbitrario. La importación solo añade modelos nuevos y respeta exclusiones.

## 13. Lotes de clientes

`ClientBatchSheet`, `ClientBatchField`, `ClientBatchRow` y `ClientBatchChange` implementan hojas/lotes configurables con cantidades, precios, cliente, observaciones, datos extra y auditoría de cambios.

## 14. Importación y exportación Excel

`inventory/services.py` procesa cada hoja como tabla dinámica. Detecta encabezados, infiere metadatos y patrón de ID y crea incidencias para columnas sin nombre, filas sin ID o IDs duplicados. La exportación crea una hoja por tabla activa.

## 15. Búsqueda

Hay búsqueda de inventario y una búsqueda global de BD por cadena completa o parcial. La global recorre tablas funcionales, convierte valores (incluido JSON) a texto y muestra coincidencias por tabla/registro/campo. Excluye contraseñas, sesiones, tokens y otros campos sensibles.

## 16. Chat, notificaciones y menú

`ChatMessage` implementa mensajería interna. Las alertas alimentan el menú lateral, organizado en grupos plegables cuyo estado se recuerda en navegador; las alertas también se muestran en encabezados de grupos cerrados.

## 17. Impresión de etiquetas

`LabelPrintJob` registra trabajos y resultado. El backend automático actual de `printing.py` es específico de Windows; en Linux la operación devuelve un error controlado si se intenta utilizar ese mecanismo.

## 18. Seguridad

- Sesiones y CSRF de Django.
- Cookies HTTPOnly y Secure cuando `DJANGO_HTTPS=true`.
- `X-Frame-Options: DENY`, `nosniff` y referrer policy.
- Caddy como frontal TLS.
- Middlewares de rutas internas, mantenimiento, seguridad runtime, acceso, cuenta e invitado.
- Registro de accesos (`ServiceAccess`) y baneos (`IPBan`).
- Centro de Seguridad, eventos y sesiones activas.
- Política horaria configurable.

### 18.1 Loopback protegido

`127.0.0.0/8` y `::1` no deben poder banearse desde la interfaz. El middleware ignora baneos loopback antiguos para que Caddy/Waitress no dejen inaccesible la aplicación desde el propio servidor.

### 18.2 Política horaria, huella y sesiones

El Gestor queda exento de política horaria. El sistema registra información de cliente/sesión y puede generar alertas por cambios de huella o actividad desde IP distintas. El Gestor puede revisar eventos y cerrar sesiones. La lógica histórica contempla cierre preventivo antes del fin de la ventana permitida.

## 19. HTTPS y certificados

Caddy es el único propietario de la redirección HTTP→HTTPS. Django mantiene `SECURE_PROXY_SSL_HEADER` pero `SECURE_SSL_REDIRECT=False` para evitar bucles. Existe un portal autenticado para descargar la CA pública e instrucciones; la clave privada de la CA no debe exponerse.

## 20. Red, DHCP y DNS

`inventory/networking.py` detecta IP/MAC de la interfaz activa y puede solicitar una reserva a un endpoint DHCP autorizado mediante `PULSIA_DHCP_RESERVATION_URL` y `PULSIA_DHCP_API_TOKEN`. No ejecuta comandos arbitrarios recibidos desde la UI.

## 21. Base de datos

### 21.1 SQLite

Ruta estándar: `/almacen/data/inventario.sqlite3`. La conexión configura `busy_timeout=10000`, `synchronous=NORMAL` y modo `WAL`. Las copias consistentes usan SQLite Backup API y `PRAGMA quick_check`.

### 21.2 PostgreSQL

Se activa si `DATABASE_URL` comienza por `postgresql://`. Algunas funciones auxiliares, especialmente el scheduler de backup interno, están implementadas específicamente para SQLite.

## 22. Backups y almacenamiento

`BackupSchedule` configura activación, hora, destino y retención. El scheduler se ejecuta dentro del proceso Django y comprueba periódicamente si corresponde realizar la copia del día. `BackupDiskConfig`, `storage_admin.py` y los daemons Linux permiten gestionar almacenamiento, montaje y copia continua.

El socket de administración privilegiada es `/run/pulsia-inventario/storage-admin.sock`.

## 23. Servicios Linux

| Servicio/elemento | Función |
|---|---|
| `pulsia-inventario.service` | Aplicación Django vía Waitress. |
| `pulsia-inventario-caddy` | Caddy dedicado del proyecto. |
| `pulsia-inventario-storage-admin.service` | Administración privilegiada de almacenamiento. |
| `pulsia-inventario-continuous-backup.service` | Protección/copia continua. |

## 24. Scripts Ubuntu y Debian

Los árboles `sistema/linux/ubuntu/` y `sistema/linux/debian/` son equivalentes. La ruta productiva estándar es `/almacen`.

| Script | Función |
|---|---|
| `00_configurar_acceso_remoto.sh` | Preparación de acceso remoto/red. |
| `01_instalar_servicio.sh` | Instalación de aplicación, entorno, servicios, HTTPS y dependencias. |
| `02_encender_servicio.sh` | Arranque. |
| `03_reiniciar_servicio.sh` | Reinicio. |
| `04_parar_servicio.sh` | Parada. |
| `05_desinstalar_servicio.sh / desinstalar_sistema.sh` | Desinstalación; revisar conservación de datos. |
| `06_crear_primer_usuario.sh` | Creación/preparación del Gestor. |
| `07_actualizar_solo_programa.sh` | Actualización solo de código. |
| `08_actualizar_programa_y_bd.sh` | Código + migraciones. |
| `09_actualizar_servidor_estructural.sh` | Actualización estructural protegida. |
| `actualizar_sistema.sh` | Motor común de los actualizadores. |

`gestionar_pulsia.sh` es el menú raíz de administración.

## 25. Actualizadores

### 25.1 Solo programa (`07`)
Sustituye código sin ejecutar migraciones. Conserva persistencia y avisa si detecta migraciones pendientes.

### 25.2 Programa + BD (`08`)
Sustituye código y ejecuta `manage.py migrate --noinput` sobre la BD ya instalada. Nunca copia encima la BD del paquete.

### 25.3 Estructural (`09`)
Es el recomendado para servidores con datos reales. Hace backup, actualiza código, aplica migraciones y calcula una huella del contenido de `InventoryTable` e `InventoryRecord` antes y después. Si cambia el inventario protegido, considera fallida la actualización y hace rollback. Las zonas pueden evolucionar mediante migraciones y no forman parte de esa protección estricta.

Los actualizadores preservan `.env`, `data/`, `backups/`, `logs/`, `certs/` y `.venv/`. Los backups previos se almacenan bajo `/almacen/backups/actualizaciones/`.

## 26. Desinstalación y reinstalación

Si una reinstalación indica que `gestor` ya existe, normalmente la BD persistente continúa presente. Esto es correcto si se quieren conservar datos. No borrar `/almacen` o `inventario.sqlite3` a ciegas. Una instalación realmente vacía implica perder inventario, usuarios, reservas, incidencias y auditoría y exige backup previo.

## 27. Cliente PULSIA

`cliente/PULSIA_Inventario_Cliente/` contiene cliente Windows/Linux, scripts de arranque e instalación, descubrimiento del servidor, configuración, credenciales locales y utilidades de plataforma. Sus `requirements*.txt` son ficheros operativos y no deben eliminarse.

## 28. Variables de entorno relevantes

| Variable | Uso |
|---|---|
| `DJANGO_SECRET_KEY` | Clave Django; también deriva el cifrado de la contraseña MySQL externa. |
| `DJANGO_DEBUG` | `false` en producción. |
| `DJANGO_ALLOWED_HOSTS` | Hosts permitidos. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Orígenes HTTPS de confianza. |
| `DJANGO_HTTPS` | Activa cookies Secure. |
| `DATABASE_URL` | SQLite por defecto o PostgreSQL. |
| `PULSIA_DHCP_RESERVATION_URL` | Endpoint autorizado de reserva DHCP. |
| `PULSIA_DHCP_API_TOKEN` | Token opcional del servicio DHCP. |

## 29. Rutas HTTP del proyecto

| Ruta | Vista | Nombre |
|---|---|---|
| `/seguridad/certificado/` | `certificate_help` | `certificate_help` |
| `/seguridad/certificado/descargar/` | `certificate_download` | `certificate_download` |
| `/produccion/pizarra/` | `production_board` | `production_board` |
| `/produccion/zonas/` | `zones_manager` | `zones_manager` |
| `/produccion/actual/` | `production_current` | `production_current` |
| `/produccion/informes/` | `production_reports` | `production_reports` |
| `/produccion/informes/excel/` | `production_export` | `production_export` |
| `/` | `dashboard` | `dashboard` |
| `/pieza/nueva/` | `add_item` | `add_item` |
| `/pieza/<int:pk>/editar/` | `edit_item` | `edit_item` |
| `/pieza/<int:pk>/eliminar/` | `delete_item` | `delete_item` |
| `/pieza/<int:pk>/detalle/` | `record_detail` | `record_detail` |
| `/pieza/<int:pk>/reservar/` | `reserve_record` | `reserve_record` |
| `/movimiento/entrega/` | `assign_item` | `assign_item` |
| `/api/objetos/` | `object_search` | `object_search` |
| `/movimiento/merma/` | `scrap_item` | `scrap_item` |
| `/trazabilidad/` | `trace` | `trace` |
| `/informes/altas/` | `entry_report` | `entry_report` |
| `/operaciones/productividad/` | `productivity_report` | `productivity_report` |
| `/lotes-clientes/` | `client_batches` | `client_batches` |
| `/lotes-clientes/<int:sheet_id>/` | `client_batches` | `client_batches_sheet` |
| `/reservas/` | `reservations_center` | `reservations_center` |
| `/prestamos/` | `loans_center` | `loans_center` |
| `/componentes/sobrante/` | `surplus_component` | `surplus_component` |
| `/seguridad/` | `security_center` | `security_center` |
| `/seguridad/politica/` | `security_policy` | `security_policy` |
| `/seguridad/huella/` | `security_fingerprint` | `security_fingerprint` |
| `/seguridad/estado-sesion/` | `security_session_state` | `security_session_state` |
| `/chat/` | `chat_center` | `chat_center` |
| `/chat/<int:user_id>/` | `chat_center` | `chat_conversation` |
| `/notificaciones/estado/` | `notification_status` | `notification_status` |
| `/impresion/` | `printing_center` | `printing_center` |
| `/tablas/` | `raw_table` | `raw_table` |
| `/tablas/<str:table>/` | `raw_table` | `raw_table_named` |
| `/tabla/<slug:slug>/` | `table_view` | `table_view` |
| `/incidencias/` | `incidents_view` | `incidents` |
| `/incidencias/<int:incident_id>/resolver/` | `incident_resolve` | `incident_resolve` |
| `/importar/` | `import_view` | `import_excel` |
| `/exportar/` | `export_view` | `export_excel` |
| `/base-datos/copia/` | `database_backup` | `database_backup` |
| `/base-datos/backups-automaticos/` | `backup_settings` | `backup_settings` |
| `/base-datos/restaurar/` | `database_restore` | `database_restore` |
| `/base-datos/vaciar/` | `truncate_inventory` | `truncate_inventory` |
| `/servidor/detener/` | `stop_service` | `stop_service` |
| `/estructura/` | `structure` | `structure` |
| `/usuarios/` | `users_panel` | `users_panel` |
| `/accesos/` | `access_control` | `access_control` |
| `/cuenta/solicitar-acceso/` | `request_access_upgrade` | `request_access_upgrade` |
| `/cuenta/cambiar-clave/` | `change_required_password` | `change_required_password` |

Django añade también las rutas estándar de autenticación desde `config/urls.py`.

## 30. Modelo de datos completo

Los modelos auxiliares/legados no deben eliminarse sin comprobar referencias y datos de instalaciones existentes.

### 30.1 `UserProfile`

| Campo | Tipo Django |
|---|---|
| `user` | `OneToOneField` |
| `role` | `CharField` |
| `must_change_password` | `BooleanField` |
| `password_reset_requested_at` | `DateTimeField` |
| `password_reset_authorized_at` | `DateTimeField` |
| `bootstrap_token_hash` | `CharField` |
| `bootstrap_expires_at` | `DateTimeField` |
| `bootstrap_used_at` | `DateTimeField` |
| `created_ip` | `GenericIPAddressField` |
| `archived_at` | `DateTimeField` |
| `archived_by` | `ForeignKey` |
| `archived_reason` | `CharField` |
| `created_at` | `DateTimeField` |
| `updated_at` | `DateTimeField` |

### 30.2 `AccessUpgradeRequest`

| Campo | Tipo Django |
|---|---|
| `user` | `OneToOneField` |
| `requested_ip` | `GenericIPAddressField` |
| `status` | `CharField` |
| `requested_at` | `DateTimeField` |
| `decided_at` | `DateTimeField` |
| `decided_by` | `ForeignKey` |
| `decision_note` | `CharField` |

### 30.3 `BackupSchedule`

| Campo | Tipo Django |
|---|---|
| `enabled` | `BooleanField` |
| `run_time` | `TimeField` |
| `destination` | `CharField` |
| `retention` | `PositiveIntegerField` |
| `last_run_at` | `DateTimeField` |
| `last_status` | `CharField` |
| `last_error` | `TextField` |
| `updated_by` | `ForeignKey` |
| `updated_at` | `DateTimeField` |

### 30.4 `BackupDiskConfig`

| Campo | Tipo Django |
|---|---|
| `mode` | `CharField` |
| `local_path` | `CharField` |
| `device` | `CharField` |
| `uuid` | `CharField` |
| `filesystem` | `CharField` |
| `mount_point` | `CharField` |
| `last_status` | `CharField` |
| `last_error` | `TextField` |
| `updated_by` | `ForeignKey` |
| `updated_at` | `DateTimeField` |

### 30.5 `SecurityAccessPolicy`

| Campo | Tipo Django |
|---|---|
| `enabled` | `BooleanField` |
| `allowed_days` | `CharField` |
| `start_time` | `TimeField` |
| `end_time` | `TimeField` |
| `logout_before_end_seconds` | `PositiveIntegerField` |
| `updated_by` | `ForeignKey` |
| `created_at` | `DateTimeField` |
| `updated_at` | `DateTimeField` |

### 30.6 `SecurityAccessEvent`

| Campo | Tipo Django |
|---|---|
| `user` | `ForeignKey` |
| `level` | `CharField` |
| `event_type` | `CharField` |
| `description` | `CharField` |
| `ip` | `GenericIPAddressField` |
| `previous_ip` | `GenericIPAddressField` |
| `previous_data` | `JSONField` |
| `current_data` | `JSONField` |
| `reviewed` | `BooleanField` |
| `reviewed_at` | `DateTimeField` |
| `reviewed_by` | `ForeignKey` |
| `resolution` | `CharField` |
| `created_at` | `DateTimeField` |

### 30.7 `ActiveSecuritySession`

| Campo | Tipo Django |
|---|---|
| `user` | `ForeignKey` |
| `session_key` | `CharField` |
| `ip` | `GenericIPAddressField` |
| `user_agent` | `TextField` |
| `browser` | `CharField` |
| `operating_system` | `CharField` |
| `language` | `CharField` |
| `timezone_name` | `CharField` |
| `screen_resolution` | `CharField` |
| `client_data` | `JSONField` |
| `fingerprint_hash` | `CharField` |
| `started_at` | `DateTimeField` |
| `last_activity` | `DateTimeField` |
| `closed` | `BooleanField` |
| `closed_at` | `DateTimeField` |

### 30.8 `InventoryTable`

| Campo | Tipo Django |
|---|---|
| `name` | `CharField` |
| `slug` | `SlugField` |
| `id_header` | `CharField` |
| `id_prefix` | `CharField` |
| `id_width` | `PositiveSmallIntegerField` |
| `next_number` | `PositiveIntegerField` |
| `position` | `PositiveIntegerField` |
| `active` | `BooleanField` |
| `created_by` | `ForeignKey` |
| `created_at` | `DateTimeField` |

### 30.9 `InventoryField`

| Campo | Tipo Django |
|---|---|
| `table` | `ForeignKey` |
| `name` | `CharField` |
| `key` | `SlugField` |
| `position` | `PositiveIntegerField` |
| `field_type` | `CharField` |
| `is_primary` | `BooleanField` |
| `is_destination_sn` | `BooleanField` |
| `is_technician` | `BooleanField` |
| `searchable` | `BooleanField` |

### 30.10 `InventoryRecord`

| Campo | Tipo Django |
|---|---|
| `table` | `ForeignKey` |
| `internal_id` | `CharField` |
| `data` | `JSONField` |
| `status` | `CharField` |
| `current_sn` | `CharField` |
| `current_technician` | `CharField` |
| `created_by` | `ForeignKey` |
| `created_at` | `DateTimeField` |
| `updated_at` | `DateTimeField` |

### 30.11 `RecordMovement`

| Campo | Tipo Django |
|---|---|
| `record` | `ForeignKey` |
| `movement_type` | `CharField` |
| `occurred_at` | `DateTimeField` |
| `technician_name` | `CharField` |
| `destination_sn` | `CharField` |
| `reason` | `TextField` |
| `registered_by` | `ForeignKey` |
| `created_at` | `DateTimeField` |

### 30.12 `Reservation`

| Campo | Tipo Django |
|---|---|
| `record` | `ForeignKey` |
| `requested_by` | `ForeignKey` |
| `destination` | `CharField` |
| `destination_sn` | `CharField` |
| `status` | `CharField` |
| `requested_at` | `DateTimeField` |
| `accepted_by` | `ForeignKey` |
| `accepted_at` | `DateTimeField` |
| `resolved_by` | `ForeignKey` |
| `resolved_at` | `DateTimeField` |

### 30.13 `LoanItem`

| Campo | Tipo Django |
|---|---|
| `internal_id` | `CharField` |
| `name` | `CharField` |
| `category` | `CharField` |
| `brand` | `CharField` |
| `model_reference` | `CharField` |
| `serial_number` | `CharField` |
| `description` | `TextField` |
| `status` | `CharField` |
| `notes` | `TextField` |
| `created_by` | `ForeignKey` |
| `created_at` | `DateTimeField` |
| `updated_at` | `DateTimeField` |

### 30.14 `LoanRequest`

| Campo | Tipo Django |
|---|---|
| `item` | `ForeignKey` |
| `requested_by` | `ForeignKey` |
| `requested_at` | `DateTimeField` |
| `status` | `CharField` |
| `notes` | `TextField` |
| `resolved_by` | `ForeignKey` |
| `resolved_at` | `DateTimeField` |

### 30.15 `Loan`

| Campo | Tipo Django |
|---|---|
| `record` | `ForeignKey` |
| `loan_item` | `ForeignKey` |
| `request` | `OneToOneField` |
| `borrower` | `ForeignKey` |
| `technician_name` | `CharField` |
| `withdrawn_at` | `DateTimeField` |
| `returned_at` | `DateTimeField` |
| `created_by` | `ForeignKey` |
| `returned_by` | `ForeignKey` |
| `notes` | `TextField` |
| `created_at` | `DateTimeField` |

### 30.16 `ReservationView`

| Campo | Tipo Django |
|---|---|
| `reservation` | `ForeignKey` |
| `user` | `ForeignKey` |
| `seen_at` | `DateTimeField` |

### 30.17 `ChatMessage`

| Campo | Tipo Django |
|---|---|
| `sender` | `ForeignKey` |
| `recipient` | `ForeignKey` |
| `body` | `TextField` |
| `created_at` | `DateTimeField` |
| `read_at` | `DateTimeField` |

### 30.18 `LabelPrintJob`

| Campo | Tipo Django |
|---|---|
| `identifier` | `CharField` |
| `copies` | `PositiveSmallIntegerField` |
| `printer_name` | `CharField` |
| `status` | `CharField` |
| `error` | `TextField` |
| `requested_by` | `ForeignKey` |
| `created_at` | `DateTimeField` |
| `completed_at` | `DateTimeField` |

### 30.19 `ClientBatchSheet`

| Campo | Tipo Django |
|---|---|
| `name` | `CharField` |
| `next_row_number` | `PositiveBigIntegerField` |
| `client` | `CharField` |
| `concept` | `CharField` |
| `position` | `PositiveIntegerField` |
| `active` | `BooleanField` |
| `created_by` | `ForeignKey` |
| `created_at` | `DateTimeField` |
| `updated_at` | `DateTimeField` |

### 30.20 `ClientBatchField`

| Campo | Tipo Django |
|---|---|
| `sheet` | `ForeignKey` |
| `name` | `CharField` |
| `key` | `SlugField` |
| `field_type` | `CharField` |
| `position` | `PositiveIntegerField` |
| `active` | `BooleanField` |
| `created_by` | `ForeignKey` |
| `created_at` | `DateTimeField` |
| `updated_at` | `DateTimeField` |

### 30.21 `ClientBatchRow`

| Campo | Tipo Django |
|---|---|
| `sheet` | `ForeignKey` |
| `internal_id` | `CharField` |
| `brand` | `CharField` |
| `model_reference` | `CharField` |
| `component` | `CharField` |
| `reference` | `CharField` |
| `units_pending` | `PositiveIntegerField` |
| `units_stock` | `PositiveIntegerField` |
| `units_sent` | `PositiveIntegerField` |
| `unit_price` | `DecimalField` |
| `total_price` | `DecimalField` |
| `client` | `CharField` |
| `observations` | `TextField` |
| `extra_data` | `JSONField` |
| `created_by` | `ForeignKey` |
| `updated_by` | `ForeignKey` |
| `created_at` | `DateTimeField` |
| `updated_at` | `DateTimeField` |

### 30.22 `ClientBatchChange`

| Campo | Tipo Django |
|---|---|
| `sheet` | `ForeignKey` |
| `row` | `ForeignKey` |
| `field` | `ForeignKey` |
| `action` | `CharField` |
| `before` | `JSONField` |
| `after` | `JSONField` |
| `changed_by` | `ForeignKey` |
| `changed_at` | `DateTimeField` |

### 30.23 `ServiceAccess`

| Campo | Tipo Django |
|---|---|
| `ip_address` | `GenericIPAddressField` |
| `user` | `ForeignKey` |
| `first_seen_at` | `DateTimeField` |
| `last_seen_at` | `DateTimeField` |
| `request_count` | `PositiveBigIntegerField` |
| `last_path` | `CharField` |
| `last_user_agent` | `CharField` |

### 30.24 `IPBan`

| Campo | Tipo Django |
|---|---|
| `ip_address` | `GenericIPAddressField` |
| `banned_by` | `ForeignKey` |
| `banned_at` | `DateTimeField` |
| `banned_until` | `DateTimeField` |
| `reason` | `CharField` |
| `revoked_at` | `DateTimeField` |
| `revoked_by` | `ForeignKey` |

### 30.25 `Category`

| Campo | Tipo Django |
|---|---|
| `name` | `CharField` |
| `prefix` | `CharField` |
| `active` | `BooleanField` |

### 30.26 `CustomField`

| Campo | Tipo Django |
|---|---|
| `category` | `ForeignKey` |
| `name` | `CharField` |
| `key` | `SlugField` |
| `field_type` | `CharField` |
| `required` | `BooleanField` |
| `searchable` | `BooleanField` |
| `reportable` | `BooleanField` |
| `options` | `JSONField` |
| `active` | `BooleanField` |

### 30.27 `Location`

| Campo | Tipo Django |
|---|---|
| `name` | `CharField` |
| `active` | `BooleanField` |

### 30.28 `Technician`

| Campo | Tipo Django |
|---|---|
| `name` | `CharField` |
| `employee_code` | `CharField` |
| `active` | `BooleanField` |

### 30.29 `Item`

| Campo | Tipo Django |
|---|---|
| `internal_id` | `CharField` |
| `category` | `ForeignKey` |
| `brand` | `CharField` |
| `model_reference` | `CharField` |
| `serial_number` | `CharField` |
| `status` | `CharField` |
| `location` | `ForeignKey` |
| `destination_sn` | `CharField` |
| `notes` | `TextField` |
| `custom_data` | `JSONField` |
| `created_at` | `DateTimeField` |
| `updated_at` | `DateTimeField` |
| `created_by` | `ForeignKey` |

### 30.30 `Movement`

| Campo | Tipo Django |
|---|---|
| `item` | `ForeignKey` |
| `movement_type` | `CharField` |
| `occurred_at` | `DateTimeField` |
| `technician` | `ForeignKey` |
| `destination_sn` | `CharField` |
| `from_location` | `ForeignKey` |
| `to_location` | `ForeignKey` |
| `reason` | `TextField` |
| `registered_by` | `ForeignKey` |
| `created_at` | `DateTimeField` |

### 30.31 `Incident`

| Campo | Tipo Django |
|---|---|
| `title` | `CharField` |
| `details` | `TextField` |
| `kind` | `CharField` |
| `severity` | `CharField` |
| `status` | `CharField` |
| `source_file` | `CharField` |
| `source_sheet` | `CharField` |
| `source_row` | `PositiveIntegerField` |
| `payload` | `JSONField` |
| `created_at` | `DateTimeField` |
| `resolved_at` | `DateTimeField` |
| `resolved_by` | `ForeignKey` |

### 30.32 `ImportJob`

| Campo | Tipo Django |
|---|---|
| `file_name` | `CharField` |
| `fingerprint` | `CharField` |
| `status` | `CharField` |
| `rows_total` | `PositiveIntegerField` |
| `rows_imported` | `PositiveIntegerField` |
| `rows_incident` | `PositiveIntegerField` |
| `created_by` | `ForeignKey` |
| `created_at` | `DateTimeField` |

### 30.33 `AuditLog`

| Campo | Tipo Django |
|---|---|
| `user` | `ForeignKey` |
| `action` | `CharField` |
| `object_type` | `CharField` |
| `object_id` | `CharField` |
| `details` | `JSONField` |
| `created_at` | `DateTimeField` |

### 30.34 `NetworkReservationRequest`

| Campo | Tipo Django |
|---|---|
| `ip_address` | `GenericIPAddressField` |
| `prefix_length` | `PositiveSmallIntegerField` |
| `gateway` | `GenericIPAddressField` |
| `mac_address` | `CharField` |
| `interface_name` | `CharField` |
| `hostname` | `CharField` |
| `platform` | `CharField` |
| `status` | `CharField` |
| `dhcp_reserved` | `BooleanField` |
| `dns_updated` | `BooleanField` |
| `details` | `JSONField` |
| `message` | `TextField` |
| `requested_by` | `ForeignKey` |
| `requested_at` | `DateTimeField` |
| `completed_at` | `DateTimeField` |

### 30.35 `ProductionModelMySQLSource`

| Campo | Tipo Django |
|---|---|
| `host` | `CharField` |
| `port` | `PositiveIntegerField` |
| `database` | `CharField` |
| `username` | `CharField` |
| `encrypted_password` | `TextField` |
| `updated_by` | `ForeignKey` |
| `updated_at` | `DateTimeField` |

### 30.36 `ProductionModel`

| Campo | Tipo Django |
|---|---|
| `name` | `CharField` |
| `is_active` | `BooleanField` |
| `created_by` | `ForeignKey` |
| `created_at` | `DateTimeField` |

### 30.37 `ProductionModelExclusion`

| Campo | Tipo Django |
|---|---|
| `name` | `CharField` |
| `excluded_by` | `ForeignKey` |
| `reason` | `CharField` |
| `created_at` | `DateTimeField` |

### 30.38 `ProductionProcessor`

| Campo | Tipo Django |
|---|---|
| `name` | `CharField` |
| `is_active` | `BooleanField` |
| `created_by` | `ForeignKey` |
| `created_at` | `DateTimeField` |

### 30.39 `ProductionZone`

| Campo | Tipo Django |
|---|---|
| `code` | `SlugField` |
| `name` | `CharField` |
| `position` | `PositiveIntegerField` |
| `is_active` | `BooleanField` |
| `created_by` | `ForeignKey` |
| `created_at` | `DateTimeField` |
| `updated_at` | `DateTimeField` |

### 30.40 `ProductionEntry`

| Campo | Tipo Django |
|---|---|
| `user` | `ForeignKey` |
| `date` | `DateField` |
| `hour` | `PositiveSmallIntegerField` |
| `model_name` | `CharField` |
| `production_model` | `ForeignKey` |
| `ram_gb` | `PositiveIntegerField` |
| `disk_gb` | `PositiveIntegerField` |
| `processor` | `ForeignKey` |
| `processor_name` | `CharField` |
| `origin_zone` | `CharField` |
| `zone` | `CharField` |
| `quantity` | `PositiveIntegerField` |
| `created_at` | `DateTimeField` |

## 31. Migraciones incluidas

- `0001_initial.py`
- `0002_userprofile.py`
- `0003_inventorytable_inventoryrecord_recordmovement_and_more.py`
- `0004_inventorytable_id_prefix_inventorytable_id_width_and_more.py`
- `0005_alter_inventoryrecord_status_and_more.py`
- `0006_chatmessage_reservationview.py`
- `0007_loans_password_reset_and_statuses.py`
- `0008_gestor_bootstrap.py`
- `0009_loan_requests_and_reservation_workflow.py`
- `0010_clientbatchsheet_clientbatchrow_clientbatchfield_and_more.py`
- `0011_clientbatchrow_brand_clientbatchrow_component_and_more.py`
- `0012_ipban_permanent.py`
- `0013_networkreservationrequest.py`
- `0014_guest_access_upgrade.py`
- `0015_workflow_backups_archived_users.py`
- `0016_access_schedule_security_policy.py`
- `0017_security_schedule_full.py`
- `0018_security_runtime_complete.py`
- `0019_production_entry.py`
- `0020_production_entry_indexes.py`
- `0021_production_model_catalog.py`
- `0022_production_model_mysql_source.py`
- `0023_production_specs_exclusions_processors.py`
- `0024_backup_disk_config.py`
- `0025_production_origin_and_local_backup.py`
- `0026_production_origin_per_entry.py`
- `0027_unified_production_zones.py`

La última migración incluida es `0027_unified_production_zones.py`. No reescribir migraciones ya aplicadas en producción; crear una nueva migración.

## 32. Reglas para futuras versiones

- No volver a hacer rígidos los campos dinámicos mediante `field_type`.
- No aceptar ni cambiar `internal_id` desde formularios de edición.
- No usar `force_insert=True` como sustituto del guardado flexible.
- Capturar fallos de persistencia y mostrarlos como error de formulario en lugar de 500.
- Todo flujo que guarde `InventoryRecord` debe pasar por el saneamiento común.
- No crear listas estáticas de zonas paralelas.
- No banear loopback.
- No sobrescribir `.env` ni la BD en actualizaciones.
- Crear backup y rollback ante cambios estructurales.
- Mantener Ubuntu y Debian alineados.
- Actualizar este documento en vez de crear `VERSION_*.txt` o README parciales.

## 33. Diagnóstico de un HTTP 500

```bash
cd /almacen
sudo systemctl status pulsia-inventario --no-pager
sudo journalctl -u pulsia-inventario -n 200 --no-pager
sudo ./.venv/bin/python manage.py check
sudo ./.venv/bin/python manage.py showmigrations
```

Obtener el traceback exacto antes de seguir modificando validaciones y comprobar que el proceso ejecuta el código recién desplegado.

## 34. Pruebas mínimas de regresión

- `manage.py check` y, cuando sea posible, `manage.py test inventory`.
- Alta/edición de batería y otros componentes con alfanumérico en cualquier campo no-ID.
- Intento de cambiar ID: debe mantenerse.
- Reserva con 2/3 campos: no reservada; con 3/3: flujo válido.
- Zonas: solo Gestor modifica.
- Búsqueda global parcial.
- Resolución de incidencia normal y forzada.
- Backup SQLite y `quick_check`.
- Actualizador estructural sobre una copia con inventario real.
- HTTPS y protección loopback.

## 35. Límites conocidos

- El scheduler de backup interno está implementado específicamente para SQLite.
- La impresión automática actual es específica de Windows.
- Existen modelos auxiliares/legados además del inventario dinámico principal; no eliminarlos sin análisis.
- Una instalación real puede contener `.env`, certificados y datos distintos a los del ZIP.

## 36. Traspaso a otro modelo de IA

Entregar al nuevo modelo **este documento y el ZIP completo vigente**. Debe verificar el código antes de cambios, trabajar siempre sobre el último ZIP, preservar la BD/inventario, respetar las invariantes de ID/campos/reservas/zonas/loopback y devolver versiones completas, no parches aislados. Si cambia arquitectura, modelos, rutas, scripts, permisos o reglas funcionales, debe actualizar este mismo documento.

## 37. Referencia rápida

```text
Framework       Django 5.2
WSGI            Waitress
Proxy HTTPS     Caddy
Ruta Linux      /almacen
Backend         127.0.0.1:8080
BD por defecto  /almacen/data/inventario.sqlite3
Timezone        Europe/Madrid
Gestor          superuser
Inventario      InventoryTable + InventoryField + InventoryRecord
Zonas           ProductionZone
Actualizador    09_actualizar_servidor_estructural.sh (recomendado)
```

---

**Documento único del proyecto.** No crear nuevas notas de versión ni README funcionales parciales; integrar aquí cualquier cambio posterior.