#!/bin/bash
# Flower — dashboard de monitoramento do Celery
# Acesse em: http://localhost:5555
exec /Volumes/D/P-Jari/venv/bin/celery \
    -A config flower \
    --port=5555 \
    --queues=fast,heavy \
    --loglevel=info
