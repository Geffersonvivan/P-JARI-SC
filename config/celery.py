import os
from celery import Celery
from celery.signals import task_postrun, worker_process_shutdown

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('config')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
app.autodiscover_tasks()


@task_postrun.connect
def close_db_connections_after_task(sender=None, **kwargs):
    """Fecha conexões DB ociosas após cada task para evitar 'too many clients'."""
    from django.db import close_old_connections
    close_old_connections()


@worker_process_shutdown.connect
def close_db_connections_on_shutdown(sender=None, **kwargs):
    """Fecha todas as conexões DB quando um worker process encerra."""
    from django.db import connections
    for conn in connections.all():
        conn.close()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
