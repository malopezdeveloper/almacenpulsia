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
    # django_migrations se protege para no romper el estado de migraciones de Django.
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
    if request.POST.get('confirm', '').strip() != f'TRUNCATE {table_name}':
        messages.error(request, f'Escribe exactamente TRUNCATE {table_name} para confirmar.')
        return redirect('developer_truncate_console')

    qn = connection.ops.quote_name
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                if connection.vendor == 'postgresql':
                    cursor.execute(f'TRUNCATE TABLE {qn(table_name)} RESTART IDENTITY CASCADE')
                elif connection.vendor == 'mysql':
                    cursor.execute('SET FOREIGN_KEY_CHECKS=0')
                    try:
                        cursor.execute(f'TRUNCATE TABLE {qn(table_name)}')
                    finally:
                        cursor.execute('SET FOREIGN_KEY_CHECKS=1')
                elif connection.vendor == 'sqlite':
                    # SQLite no implementa TRUNCATE. DELETE + sqlite_sequence reproduce
                    # el efecto práctico de vaciar la tabla y reiniciar su autoincremento.
                    cursor.execute(f'DELETE FROM {qn(table_name)}')
                    try:
                        cursor.execute('DELETE FROM sqlite_sequence WHERE name=%s', [table_name])
                    except Exception:
                        pass
                else:
                    cursor.execute(f'DELETE FROM {qn(table_name)}')
        messages.warning(request, f'DESARROLLO: TRUNCATE ejecutado sobre {table_name}.')
    except Exception as exc:
        messages.error(request, f'No se pudo truncar {table_name}: {exc}')
    return redirect('developer_truncate_console')
