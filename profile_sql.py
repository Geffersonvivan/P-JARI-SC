import os
import django
import time

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from django.db import connection

def run_sql_profile():
    c = Client()
    u = User.objects.first()
    c.force_login(u)
    
    from legal.models import DocumentoLegal, AceiteDocumentoLegal
    termo = DocumentoLegal.objects.filter(tipo='TERMO_USO', is_active=True).first()
    if termo: AceiteDocumentoLegal.objects.get_or_create(user=u, documento=termo)
    politica = DocumentoLegal.objects.filter(tipo='POLITICA_PRIVACIDADE', is_active=True).first()
    if politica: AceiteDocumentoLegal.objects.get_or_create(user=u, documento=politica)
    
    # Enable query logging
    # Note: DEBUG must be True to capture queries normally, or we force it by executing
    from django.conf import settings
    settings.DEBUG = True
    
    start_time = time.time()
    response = c.get('/app/', HTTP_HOST='localhost')
    end_time = time.time()
    
    print(f"Total Response Time: {end_time - start_time:.3f}s")
    print(f"Status Code: {response.status_code}")
    if response.status_code in (301, 302):
        print(f"Redirected to: {response.url}")
    print(f"Total SQL Queries: {len(connection.queries)}")
    
    # Sort queries by time
    queries = sorted(connection.queries, key=lambda q: float(q['time']), reverse=True)
    
    print("\n--- Top 10 Slowest Queries ---")
    for idx, q in enumerate(queries[:10]):
        print(f"[{idx+1}] Time: {q['time']}s")
        print(f"SQL: {q['sql'][:500]}...\n")

if __name__ == '__main__':
    run_sql_profile()
