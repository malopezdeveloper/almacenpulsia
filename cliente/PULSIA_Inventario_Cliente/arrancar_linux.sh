#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
VENV="$ROOT/.dev-venv-linux"
PYTHON="$VENV/bin/python"
REQ="$ROOT/requirements.txt"
STAMP="$VENV/.requirements.sha256"

if [[ ! -f "$REQ" ]]; then
  echo "[ERROR] No existe requirements.txt" >&2
  exit 1
fi

if [[ ! -x "$PYTHON" ]]; then
  BASE=""
  CANDIDATES=(python3.13 python3.12 python3.11 python3.10 python3)
  # El instalador del servidor PULSIA puede dejar Python en /opt/pulsia.
  for custom in /opt/pulsia/python-*/bin/python3.*; do
    [[ -x "$custom" ]] && CANDIDATES+=("$custom")
  done
  for p in "${CANDIDATES[@]}"; do
    if command -v "$p" >/dev/null 2>&1 || [[ -x "$p" ]]; then
      if "$p" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' >/dev/null 2>&1; then
        BASE="$p"
        break
      fi
    fi
  done
  if [[ -z "$BASE" ]]; then
    echo '[ERROR] Se necesita Python 3.10 o superior.' >&2
    exit 1
  fi
  echo "[INFO] Creando entorno virtual con $BASE..."
  "$BASE" -m venv "$VENV"
fi

HASH="$(sha256sum "$REQ" | awk '{print $1}')"
OLD="$(cat "$STAMP" 2>/dev/null || true)"
if [[ "$HASH" != "$OLD" ]] || ! "$PYTHON" -c 'import PySide6,keyring,psutil' >/dev/null 2>&1; then
  echo '[INFO] Instalando dependencias...'
  "$PYTHON" -m pip install --upgrade pip
  "$PYTHON" -m pip install -r "$REQ"
  printf '%s\n' "$HASH" > "$STAMP"
fi

"$PYTHON" -c "import PySide6,keyring,psutil; from PySide6.QtWebEngineWidgets import QWebEngineView; print('[OK] PySide6/QtWebEngine/keyring/psutil')"
"$PYTHON" -m compileall -q "$ROOT/src"
exec "$PYTHON" "$ROOT/src/main.py"
