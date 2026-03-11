import os
import django
import time

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import Client
from django.contrib.auth.models import User

# Instrumenting chat/views.py with prints
# Actually, let's just use cProfile
import cProfile
import pstats

def run_profile():
    c = Client()
    u = User.objects.first()
    c.force_login(u)
    
    profiler = cProfile.Profile()
    profiler.enable()
    
    response = c.get('/estatisticas/', HTTP_HOST='localhost')
    
    profiler.disable()
    stats = pstats.Stats(profiler).sort_stats('tottime')
    stats.print_stats(20)

if __name__ == '__main__':
    run_profile()
