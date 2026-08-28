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
            cursor.execute(
                """
                SELECT DISTINCT Manufacturer, Model
                FROM Units
                WHERE NULLIF(TRIM(Manufacturer), '') IS NOT NULL
                   OR NULLIF(TRIM(Model), '') IS NOT NULL
                ORDER BY Manufacturer, Model
                """
            )
            return cursor.fetchall()
    finally:
        conn.close()


def normalize_model(manufacturer, model):
    manufacturer = " ".join(str(manufacturer or "").strip().split())
    model = " ".join(str(model or "").strip().split())
    name = " ".join(part for part in (manufacturer, model) if part).strip().upper()
    return name
