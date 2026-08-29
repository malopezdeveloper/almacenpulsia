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
    return pymysql.connect(
        host=config.host,
        port=config.port,
        user=config.username,
        password=decrypt_password(config.encrypted_password),
        database=config.database,
        charset="utf8mb4",
        autocommit=True,
        connect_timeout=5,
        read_timeout=15,
        write_timeout=15,
        cursorclass=pymysql.cursors.Cursor,
    )


def test_source(config):
    conn = connect_mysql(config)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.execute("SELECT Manufacturer, Model FROM Units LIMIT 1")
            cursor.fetchone()
    finally:
        conn.close()


def fetch_models(config):
    conn = connect_mysql(config)
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT DISTINCT Manufacturer, Model
                FROM Units
                WHERE NULLIF(TRIM(Manufacturer), '') IS NOT NULL
                   OR NULLIF(TRIM(Model), '') IS NOT NULL
                ORDER BY Manufacturer, Model
            """)
            return cursor.fetchall()
    finally:
        conn.close()


def normalize_model(manufacturer, model):
    manufacturer = " ".join(str(manufacturer or "").strip().split())
    model = " ".join(str(model or "").strip().split())
    name = " ".join(part for part in (manufacturer, model) if part).strip().upper()
    return name


def _units_columns(conn):
    with conn.cursor() as cursor:
        cursor.execute("SHOW COLUMNS FROM Units")
        return [row[0] for row in cursor.fetchall()]


def _pick(columns, *candidates):
    lower={c.lower():c for c in columns}
    for candidate in candidates:
        if candidate.lower() in lower:
            return lower[candidate.lower()]
    return None


def _aiken_map(conn):
    cols=_units_columns(conn)
    return {
        'id':_pick(cols,'UnitID','ID','Id'),
        'serial_number':_pick(cols,'SerialNumber','Serial','SN','ServiceTag'),
        'lot':_pick(cols,'LotID','Lot','LotNumber','BatchID'),
        'brand':_pick(cols,'Manufacturer','Brand','Marca'),
        'model':_pick(cols,'Model','Modelo'),
        'processor':_pick(cols,'Processor','CPU','ProcessorName'),
        'ram':_pick(cols,'RAM','Memory','MemorySize'),
        'disk':_pick(cols,'Disk','Storage','HDD','SSD'),
    }


def _select_expr(mapping):
    parts=[]
    for alias,column in mapping.items():
        if column:
            parts.append(f"`{column}` AS `{alias}`")
        else:
            parts.append(f"NULL AS `{alias}`")
    return ', '.join(parts)


def search_aiken_units(config, serial_query='', lot=None, limit=50):
    """Consulta AIKEN únicamente en lectura. Devuelve dicts normalizados."""
    conn=connect_mysql(config)
    try:
        mapping=_aiken_map(conn)
        if not mapping['serial_number']:
            raise ValueError('La tabla Units de AIKEN no contiene una columna de número de serie reconocible.')
        where=[]; params=[]
        if serial_query:
            where.append(f"`{mapping['serial_number']}` LIKE %s")
            params.append(f"%{serial_query}%")
        if lot is not None and str(lot).strip():
            if not mapping['lot']:
                raise ValueError('La tabla Units de AIKEN no contiene una columna de lote reconocible.')
            where.append(f"CAST(`{mapping['lot']}` AS CHAR)=%s")
            params.append(str(lot).strip())
        sql=f"SELECT {_select_expr(mapping)} FROM Units"
        if where: sql+=' WHERE '+' AND '.join(where)
        sql+=f" ORDER BY `{mapping['serial_number']}` LIMIT %s"
        params.append(max(1,min(int(limit),5000)))
        with conn.cursor() as cursor:
            cursor.execute(sql,params)
            names=[d[0] for d in cursor.description]
            return [dict(zip(names,row)) for row in cursor.fetchall()]
    finally:
        conn.close()


def list_aiken_lots(config, query='', limit=100):
    conn=connect_mysql(config)
    try:
        mapping=_aiken_map(conn)
        if not mapping['lot']:
            raise ValueError('La tabla Units de AIKEN no contiene una columna de lote reconocible.')
        col=mapping['lot']; params=[]
        sql=f"SELECT CAST(`{col}` AS CHAR) lote, COUNT(*) total FROM Units"
        if query:
            sql+=f" WHERE CAST(`{col}` AS CHAR) LIKE %s"; params.append(f"%{query}%")
        sql+=f" GROUP BY `{col}` ORDER BY `{col}` DESC LIMIT %s"; params.append(max(1,min(int(limit),500)))
        with conn.cursor() as cursor:
            cursor.execute(sql,params)
            return [{'lot':row[0],'total':row[1]} for row in cursor.fetchall()]
    finally:
        conn.close()
