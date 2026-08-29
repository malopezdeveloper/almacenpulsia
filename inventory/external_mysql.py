import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet():
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_password(value):
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_password(value):
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError) as exc:
        raise ValueError("No se puede descifrar la contraseña MySQL. Compruebe que DJANGO_SECRET_KEY no haya cambiado.") from exc


def connect_mysql(config):
    import pymysql
    return pymysql.connect(host=config.host,port=config.port,user=config.username,password=decrypt_password(config.encrypted_password),database=config.database,charset="utf8mb4",autocommit=True,connect_timeout=5,read_timeout=15,write_timeout=15,cursorclass=pymysql.cursors.Cursor)


def _units_columns(conn):
    with conn.cursor() as cursor:
        cursor.execute("SHOW COLUMNS FROM Units")
        return [row[0] for row in cursor.fetchall()]


def _pick(columns, *candidates):
    lower={c.lower():c for c in columns}
    for candidate in candidates:
        if candidate.lower() in lower:return lower[candidate.lower()]
    return None


def _aiken_map(conn):
    cols=_units_columns(conn)
    return {'id':_pick(cols,'UnitID','ID','Id'),'serial_number':_pick(cols,'SerialNumber','Serial','SN','ServiceTag'),'lot':_pick(cols,'LotID','Lot','LotNumber','BatchID'),'brand':_pick(cols,'Manufacturer','Brand','Marca'),'model':_pick(cols,'Model','Modelo'),'processor':_pick(cols,'Processor','CPU','ProcessorName'),'ram':_pick(cols,'RAM','Memory','MemorySize'),'disk':_pick(cols,'Disk','Storage','HDD','SSD')}


def test_source(config):
    conn=connect_mysql(config)
    try:
        mapping=_aiken_map(conn)
        if not mapping['serial_number']:
            raise ValueError('La tabla Units no contiene una columna de número de serie reconocible.')
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT `{mapping['serial_number']}` FROM Units LIMIT 1")
            cursor.fetchone()
    finally:conn.close()


def fetch_models(config):
    conn=connect_mysql(config)
    try:
        mapping=_aiken_map(conn); brand=mapping['brand']; model=mapping['model']
        if not brand and not model:return []
        brand_expr=f"`{brand}`" if brand else "NULL"; model_expr=f"`{model}`" if model else "NULL"
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT DISTINCT {brand_expr}, {model_expr} FROM Units ORDER BY 1,2")
            return cursor.fetchall()
    finally:conn.close()


def normalize_model(manufacturer, model):
    manufacturer=" ".join(str(manufacturer or "").strip().split());model=" ".join(str(model or "").strip().split())
    return " ".join(part for part in (manufacturer,model) if part).strip().upper()


def _select_expr(mapping):
    return ', '.join(f"`{column}` AS `{alias}`" if column else f"NULL AS `{alias}`" for alias,column in mapping.items())


def search_aiken_units(config, serial_query='', lot=None, limit=50, exact_serial=False):
    """Consulta AIKEN solo en lectura. exact_serial evita incorporar coincidencias parciales."""
    conn=connect_mysql(config)
    try:
        mapping=_aiken_map(conn)
        if not mapping['serial_number']:raise ValueError('La tabla Units de AIKEN no contiene una columna de número de serie reconocible.')
        where=[];params=[]
        if serial_query:
            if exact_serial:
                where.append(f"TRIM(CAST(`{mapping['serial_number']}` AS CHAR))=%s");params.append(str(serial_query).strip())
            else:
                where.append(f"`{mapping['serial_number']}` LIKE %s");params.append(f"%{serial_query}%")
        if lot is not None and str(lot).strip():
            if not mapping['lot']:raise ValueError('La tabla Units de AIKEN no contiene una columna de lote reconocible.')
            where.append(f"CAST(`{mapping['lot']}` AS CHAR)=%s");params.append(str(lot).strip())
        sql=f"SELECT {_select_expr(mapping)} FROM Units"+((' WHERE '+' AND '.join(where)) if where else '')+f" ORDER BY `{mapping['serial_number']}` LIMIT %s";params.append(max(1,min(int(limit),5000)))
        with conn.cursor() as cursor:
            cursor.execute(sql,params);names=[d[0] for d in cursor.description];return [dict(zip(names,row)) for row in cursor.fetchall()]
    finally:conn.close()


def find_aiken_unit_exact(config, serial_number):
    rows=search_aiken_units(config,serial_query=serial_number,limit=2,exact_serial=True)
    return rows[0] if rows else None


def list_aiken_lots(config, query='', limit=100):
    conn=connect_mysql(config)
    try:
        mapping=_aiken_map(conn)
        if not mapping['lot']:raise ValueError('La tabla Units de AIKEN no contiene una columna de lote reconocible.')
        col=mapping['lot'];params=[];sql=f"SELECT CAST(`{col}` AS CHAR) lote, COUNT(*) total FROM Units"
        if query:sql+=f" WHERE CAST(`{col}` AS CHAR) LIKE %s";params.append(f"%{query}%")
        sql+=f" GROUP BY `{col}` ORDER BY `{col}` DESC LIMIT %s";params.append(max(1,min(int(limit),500)))
        with conn.cursor() as cursor:
            cursor.execute(sql,params);return [{'lot':row[0],'total':row[1]} for row in cursor.fetchall()]
    finally:conn.close()
