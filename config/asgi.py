"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

_django_app = get_asgi_application()


async def application(scope, receive, send):
    # Uvicorn envia eventos 'lifespan' ao iniciar/parar.
    # O handler ASGI do Django não suporta lifespan e levanta ValueError.
    # Ignoramos silenciosamente para evitar o erro no Sentry.
    if scope['type'] == 'lifespan':
        return
    await _django_app(scope, receive, send)
