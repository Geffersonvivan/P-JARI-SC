import os
import django
import time

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from django.conf import settings
from django.db import connection

settings.DEBUG = True

def run_profile():
    connection.queries_log.clear()
    c = Client()
    u = User.objects.first()
    c.force_login(u)
    
    t0 = time.time()
    response = c.get('/estatisticas/', HTTP_HOST='localhost')
    print(f"Total time: {time.time()-t0:.2f}s")
    
    queries = connection.queries
    queries.sort(key=lambda q: float(q['time']), reverse=True)
    
    print('============= SLOWEST QUERIES =============')
    for q in queries[:10]:
        print(f"Time: {q['time']} - SQL: {q['sql'][:500]}...")

if __name__ == '__main__':
    run_profile()
