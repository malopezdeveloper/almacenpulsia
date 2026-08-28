import os
import sqlite3
import tempfile
from pathlib import Path

from django.db.backends.signals import connection_created


def _configure_sqlite_connection(sender, connection, **kwargs):
    if connection.vendor != "sqlite":
        return
    cursor = connection.cursor()
    try:
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        current = cursor.execute("PRAGMA journal_mode").fetchone()[0]
        if str(current).lower() != "wal":
            cursor.execute("PRAGMA journal_mode=WAL")
    finally:
        cursor.close()


def install_sqlite_pragmas():
    connection_created.connect(_configure_sqlite_connection, dispatch_uid="pulsia_sqlite_pragmas")


def create_sqlite_snapshot(source_path, destination_path=None):
    source_path = Path(source_path)
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    if destination_path is None:
        fd, name = tempfile.mkstemp(prefix="pulsia_sqlite_", suffix=".sqlite3")
        os.close(fd)
        destination_path = Path(name)
    else:
        destination_path = Path(destination_path)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True, timeout=10)
    destination = sqlite3.connect(destination_path, timeout=10)
    try:
        source.execute("PRAGMA busy_timeout=10000")
        source.backup(destination, pages=256, sleep=0.05)
        check = destination.execute("PRAGMA quick_check").fetchone()[0]
        if check != "ok":
            raise RuntimeError(f"La copia SQLite no supera quick_check: {check}")
        destination.commit()
    finally:
        destination.close()
        source.close()
    return destination_path


class DeleteOnCloseFile:
    def __init__(self, path):
        self.path = Path(path)
        self.file = self.path.open("rb")
    def __getattr__(self, name):
        return getattr(self.file, name)
    def close(self):
        try:
            self.file.close()
        finally:
            self.path.unlink(missing_ok=True)
