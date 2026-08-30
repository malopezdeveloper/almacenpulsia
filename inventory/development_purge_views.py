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
    if not user_is_manager(request.user): return _deny()
    tables = [{'name': name, 'count': _row_count(name)} for name in _table_names()]
    return render(request, 'inventory/development_truncate_console.html', {'database_vendor': connection.vendor, 'database_tables': tables})


def _delete_table_now(table_name):
    qn = connection.ops.quote_name
    with connection.cursor() as cursor:
        cursor.execute(f'DELETE FROM {qn(table_name)}')
        if connection.vendor == 'sqlite':
            try: cursor.execute('DELETE FROM sqlite_sequence WHERE name=%s', [table_name])
            except Exception: pass
        elif connection.vendor == 'mysql':
            try: cursor.execute(f'ALTER TABLE {qn(table_name)} AUTO_INCREMENT = 1')
            except Exception: pass


@login_required
@require_POST
def truncate_table(request, table_name):
    if not user_is_manager(request.user): return _deny()
    if table_name not in set(_table_names()):
        messages.error(request, 'La tabla indicada no existe o está protegida.')
        return redirect('developer_truncate_console')
    qn = connection.ops.quote_name
    try:
        if connection.vendor == 'postgresql':
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(f'TRUNCATE TABLE {qn(table_name)} RESTART IDENTITY CASCADE')
        elif connection.vendor == 'mysql':
            with connection.cursor() as cursor:
                cursor.execute('SET FOREIGN_KEY_CHECKS=0')
                try: cursor.execute(f'TRUNCATE TABLE {qn(table_name)}')
                finally: cursor.execute('SET FOREIGN_KEY_CHECKS=1')
        elif connection.vendor == 'sqlite':
            # PRAGMA foreign_keys no puede desactivarse dentro de atomic().
            with connection.cursor() as cursor: cursor.execute('PRAGMA foreign_keys=OFF')
            try: _delete_table_now(table_name)
            finally:
                with connection.cursor() as cursor: cursor.execute('PRAGMA foreign_keys=ON')
        else:
            with transaction.atomic(): _delete_table_now(table_name)
        messages.warning(request, f'DESARROLLO: {table_name} vaciada inmediatamente.')
    except Exception as exc:
        messages.error(request, f'No se pudo vaciar {table_name}: {exc}')
    return redirect('developer_truncate_console')


SMART_RESET_KEEP_EXACT = {'django_migrations', 'django_content_type', 'django_session'}
SMART_RESET_KEEP_PREFIXES = ('auth_',)
SMART_RESET_KEEP_FRAGMENTS = (
    'userprofile', 'businessrole', 'businessroleassignment', 'responsibility',
    'inventorytable', 'inventoryfield', 'productionzone', 'productionmodel',
    'productionprocessor', 'mysqlsource', 'backupschedule', 'backupdiskconfig',
    'securityaccesspolicy',
)


def _smart_reset_tables():
    result=[]
    for name in _table_names():
        low=name.lower()
        if name in SMART_RESET_KEEP_EXACT: continue
        if any(low.startswith(p) for p in SMART_RESET_KEEP_PREFIXES): continue
        if any(f in low for f in SMART_RESET_KEEP_FRAGMENTS): continue
        result.append(name)
    return result


def _sqlite_smart_reset(tables):
    # SQLite exige cambiar foreign_keys fuera de una transacción. El código anterior
    # lo hacía dentro de transaction.atomic(), por lo que el PRAGMA no surtía efecto
    # y aparecía el error 500 al borrar tablas relacionadas.
    with connection.cursor() as cursor:
        cursor.execute('PRAGMA foreign_keys=OFF')
    try:
        qn=connection.ops.quote_name
        with connection.cursor() as cursor:
            for table in tables:
                cursor.execute(f'DELETE FROM {qn(table)}')
            try:
                placeholders=','.join(['%s']*len(tables))
                if placeholders: cursor.execute(f'DELETE FROM sqlite_sequence WHERE name IN ({placeholders})', tables)
            except Exception: pass
    finally:
        with connection.cursor() as cursor:
            cursor.execute('PRAGMA foreign_keys=ON')


@login_required
@require_POST
def smart_reset(request):
    if not user_is_manager(request.user): return _deny()
    tables=_smart_reset_tables()
    qn=connection.ops.quote_name
    try:
        if connection.vendor == 'sqlite':
            _sqlite_smart_reset(tables)
        elif connection.vendor == 'mysql':
            # TRUNCATE hace commits implícitos en MySQL; no debe envolverse en atomic().
            with connection.cursor() as cursor:
                cursor.execute('SET FOREIGN_KEY_CHECKS=0')
                try:
                    for table in tables: cursor.execute(f'TRUNCATE TABLE {qn(table)}')
                finally: cursor.execute('SET FOREIGN_KEY_CHECKS=1')
        elif connection.vendor == 'postgresql':
            with transaction.atomic(), connection.cursor() as cursor:
                for table in tables: cursor.execute(f'TRUNCATE TABLE {qn(table)} RESTART IDENTITY CASCADE')
        else:
            with transaction.atomic():
                for table in tables: _delete_table_now(table)
        messages.warning(request, f'DESARROLLO: limpieza inteligente completada. {len(tables)} tablas operativas vaciadas; usuarios, permisos, estructura de inventario y zonas conservados.')
    except Exception as exc:
        messages.error(request, f'No se pudo completar la limpieza inteligente: {exc}')
    return redirect('developer_center')
