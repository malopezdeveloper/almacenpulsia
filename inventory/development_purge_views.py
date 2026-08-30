from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import connection, transaction
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .permissions import user_is_manager


def _deny():
    return HttpResponseForbidden('Esta herramienta temporal de desarrollo es exclusiva del Gestor.')


def _table_names():
    with connection.cursor() as cursor:
        names = connection.introspection.table_names(cursor)
    return sorted(name for name in names if name != 'django_migrations')


def _row_count(table_name):
    qn = connection.ops.quote_name
    try:
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT COUNT(*) FROM {qn(table_name)}')
            return cursor.fetchone()[0]
    except Exception:
        return None


@login_required
def truncate_console(request):
    if not user_is_manager(request.user):
        return _deny()
    tables = [{'name': name, 'count': _row_count(name)} for name in _table_names()]
    return render(request, 'inventory/development_truncate_console.html', {'database_vendor': connection.vendor, 'database_tables': tables})


@login_required
@require_POST
def truncate_table(request, table_name):
    if not user_is_manager(request.user):
        return _deny()
    allowed = set(_table_names())
    if table_name not in allowed:
        messages.error(request, 'La tabla indicada no existe o está protegida.')
        return redirect('developer_truncate_console')
    qn = connection.ops.quote_name
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                if connection.vendor == 'postgresql': cursor.execute(f'TRUNCATE TABLE {qn(table_name)} RESTART IDENTITY CASCADE')
                elif connection.vendor == 'mysql':
                    cursor.execute('SET FOREIGN_KEY_CHECKS=0')
                    try: cursor.execute(f'TRUNCATE TABLE {qn(table_name)}')
                    finally: cursor.execute('SET FOREIGN_KEY_CHECKS=1')
                elif connection.vendor == 'sqlite':
                    cursor.execute(f'DELETE FROM {qn(table_name)}')
                    try: cursor.execute('DELETE FROM sqlite_sequence WHERE name=%s', [table_name])
                    except Exception: pass
                else: cursor.execute(f'DELETE FROM {qn(table_name)}')
        messages.warning(request, f'DESARROLLO: {table_name} vaciada inmediatamente.')
    except Exception as exc:
        messages.error(request, f'No se pudo vaciar {table_name}: {exc}')
    return redirect('developer_truncate_console')


# Configuración que debe sobrevivir a las pruebas: usuarios/permisos, sesiones,
# migraciones, estructura del inventario y zonas/configuración de producción.
SMART_RESET_KEEP_EXACT = {
    'django_migrations', 'django_content_type', 'django_session',
}
SMART_RESET_KEEP_PREFIXES = (
    'auth_',
)
SMART_RESET_KEEP_FRAGMENTS = (
    'userprofile', 'businessrole', 'businessroleassignment', 'responsibility',
    'inventorytable', 'inventoryfield',
    'productionzone', 'productionmodel', 'productionprocessor', 'mysqlsource',
    'backupschedule', 'backupdiskconfig', 'securityaccesspolicy',
)


def _smart_reset_tables():
    result = []
    for name in _table_names():
        low = name.lower()
        if name in SMART_RESET_KEEP_EXACT: continue
        if any(low.startswith(prefix) for prefix in SMART_RESET_KEEP_PREFIXES): continue
        if any(fragment in low for fragment in SMART_RESET_KEEP_FRAGMENTS): continue
        result.append(name)
    return result


@login_required
@require_POST
def smart_reset(request):
    """Borrado instantáneo de datos operativos para ciclos de prueba.

    Se hace a nivel SQL con restricciones FK temporalmente desactivadas cuando el
    motor lo permite. Así se elimina el grafo completo de datos de prueba sin
    depender del orden de los modelos, conservando configuración y usuarios.
    """
    if not user_is_manager(request.user):
        return _deny()
    tables = _smart_reset_tables()
    qn = connection.ops.quote_name
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                if connection.vendor == 'mysql': cursor.execute('SET FOREIGN_KEY_CHECKS=0')
                elif connection.vendor == 'sqlite': cursor.execute('PRAGMA foreign_keys=OFF')
                try:
                    for table in tables:
                        if connection.vendor == 'postgresql':
                            cursor.execute(f'TRUNCATE TABLE {qn(table)} RESTART IDENTITY CASCADE')
                        else:
                            cursor.execute(f'DELETE FROM {qn(table)}')
                            if connection.vendor == 'sqlite':
                                try: cursor.execute('DELETE FROM sqlite_sequence WHERE name=%s', [table])
                                except Exception: pass
                    if connection.vendor == 'mysql':
                        for table in tables:
                            try: cursor.execute(f'ALTER TABLE {qn(table)} AUTO_INCREMENT = 1')
                            except Exception: pass
                finally:
                    if connection.vendor == 'mysql': cursor.execute('SET FOREIGN_KEY_CHECKS=1')
                    elif connection.vendor == 'sqlite': cursor.execute('PRAGMA foreign_keys=ON')
        messages.warning(request, f'DESARROLLO: limpieza inteligente completada. {len(tables)} tablas operativas vaciadas; usuarios, permisos, estructura de inventario y zonas conservados.')
    except Exception as exc:
        messages.error(request, f'No se pudo completar la limpieza inteligente: {exc}')
    return redirect('developer_center')
