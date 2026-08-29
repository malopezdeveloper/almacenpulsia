# PULSIA Almacén — Documentación maestra del servidor

**Estado consolidado:** 29/08/2026  
**Versión funcional documentada:** v33.4 consolidada + política de backup/rollback de actualización  

> Este documento sigue siendo la referencia maestra. Los cambios de arquitectura, instalación, actualización o recuperación deben documentarse aquí.

## Regla operativa prioritaria: instalación, actualización y recuperación

PULSIA Almacén se mantiene siempre contemplando dos caminos de despliegue con la misma importancia: **instalación limpia** y **actualización de un servidor existente**. Todo cambio futuro debe funcionar en ambos escenarios y preservar los datos reales del servidor.

La actualización nunca debe sobrescribir la base de datos de producción con una base incluida en un paquete, ni eliminar `.env`, `data/`, `backups/`, `logs/`, `certs/` o `.venv/`.

Antes de copiar código o aplicar migraciones, `sistema/linux/{debian,ubuntu}/actualizar_sistema.sh` crea obligatoriamente un backup previo en:

`/almacen/backups/actualizaciones/<AAAAMMDD_HHMMSS>/`

El backup contiene:

- `codigo_previo.tar.gz`: código anterior del servidor.
- `inventario.sqlite3`: snapshot de SQLite cuando existe.
- `.env`: configuración anterior cuando existe.
- `systemd/`: unidades systemd de PULSIA presentes en el servidor.
- `backup_info.txt`: fecha, modo, host y origen de la actualización.

El enlace `/almacen/backups/actualizaciones/ultimo` identifica el backup más reciente.

El actualizador mantiene rollback automático si la propia actualización falla. Además existe un mecanismo manual independiente para recuperar el servidor después de una actualización aparentemente terminada pero defectuosa:

- `sistema/linux/debian/10_volver_atras_actualizacion.sh`
- `sistema/linux/ubuntu/10_volver_atras_actualizacion.sh`

Uso habitual:

```bash
sudo ./10_volver_atras_actualizacion.sh ultimo
```

También admite un identificador `AAAAMMDD_HHMMSS` o la ruta completa del backup. Requiere escribir literalmente `VOLVER ATRAS` antes de restaurar, salvo ejecución automatizada explícita con `PULSIA_ROLLBACK_YES=1`.

La vuelta atrás detiene los servicios, restaura código, SQLite, `.env` y unidades systemd disponibles, conserva `backups/`, `logs/` y `certs/`, ejecuta `manage.py check`, recarga systemd y vuelve a arrancar los servicios principales.

### Invariantes de recuperación

1. Ninguna versión futura puede eliminar o eludir el backup previo obligatorio.
2. Debian y Ubuntu deben mantenerse equivalentes.
3. Si se añade un nuevo servicio necesario para ejecutar Almacén, debe añadirse también al backup y rollback.
4. Si se añade un nuevo almacén persistente de datos, debe definirse explícitamente cómo se protege y restaura.
5. Las migraciones ya aplicadas no se reescriben; se crean migraciones nuevas.
6. El ID interno del inventario nunca se modifica ni duplica.
7. El actualizador estructural debe seguir protegiendo `InventoryTable` e `InventoryRecord` y revertir ante cambios no deseados.
8. Las IP loopback `127.0.0.0/8` y `::1` nunca se bloquean.

## Arquitectura esencial

Django 5.2 funciona normalmente en `/almacen`, servido por Waitress en `127.0.0.1:8080` y Caddy como frontal HTTPS. SQLite se encuentra por defecto en `/almacen/data/inventario.sqlite3`; PostgreSQL puede configurarse mediante `DATABASE_URL`.

Servicios Linux principales:

- `pulsia-inventario.service`
- `pulsia-inventario-caddy.service`
- `pulsia-inventario-storage-admin.service`
- `pulsia-inventario-continuous-backup.service`

Los scripts principales de ambos árboles `sistema/linux/debian/` y `sistema/linux/ubuntu/` incluyen instalación (`01_instalar_servicio.sh`), actualizaciones (`07`, `08`, `09` y `actualizar_sistema.sh`) y recuperación (`10_volver_atras_actualizacion.sh`).

## Invariantes funcionales heredados de v33.4

- `InventoryRecord.internal_id` es inmutable.
- Todos los campos dinámicos distintos del ID admiten texto alfanumérico.
- `InventoryRecord.save()` sanea JSON antes de persistirlo.
- Una reserva válida exige objeto + zona/destino + SN destino.
- Producción, Reservas y Componentes sobrantes usan `ProductionZone` como catálogo único.
- Solo Gestor/superuser modifica el catálogo maestro de zonas.
- Los duplicados de ID generan incidencia y nunca sobrescriben automáticamente.
- El guardado forzado nunca permite cambiar o duplicar un ID.
- Las cuentas retiradas se desactivan/archivan para preservar históricos.
- La búsqueda global excluye secretos, contraseñas, sesiones y tokens.

## Regla para futuros cambios

Antes de entregar una modificación se debe revisar expresamente:

1. comportamiento en instalación limpia;
2. comportamiento al actualizar una instalación existente;
3. migraciones necesarias;
4. persistencia que debe conservarse;
5. backup previo;
6. posibilidad real de vuelta atrás;
7. equivalencia Debian/Ubuntu;
8. `manage.py check` y pruebas aplicables.

Esta política forma parte de la arquitectura del proyecto y no es una función opcional.
