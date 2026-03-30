#!/bin/bash
# Script de inicialização do Celery Worker — P-JARI
# Chamado pelo launchd (~/Library/LaunchAgents/com.pjari.celery-worker.plist)

PROJECT_DIR="/Volumes/D/P-Jari"
PYTHON="$PROJECT_DIR/venv/bin/python3"

cd "$PROJECT_DIR"

# Exporta variáveis do .env via Python (evita problemas com caracteres especiais no bash)
eval "$(/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 - <<'PYEOF'
import os
from pathlib import Path

env_file = Path("/Volumes/D/P-Jari/.env")
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, val = line.partition('=')
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        # Escapar aspas simples no valor para o eval do bash
        val_escaped = val.replace("'", "'\\''")
        print(f"export {key}='{val_escaped}'")
PYEOF
)"

exec "$PYTHON" -m celery -A config worker \
    --loglevel=info \
    --concurrency=2 \
    --logfile="$PROJECT_DIR/logs/celery-worker.log" \
    --pidfile="$PROJECT_DIR/logs/celery-worker.pid"
