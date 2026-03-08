import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.http import Http404

try:
    raise Http404("foo")
except Exception as e:
    print("Caught!", type(e))
