import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
print("KEY:", bool(os.environ.get('GEMINI_API_KEY')))
