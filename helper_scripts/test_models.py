import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

import requests

API_KEY = os.environ.get('GEMINI_API_KEY')
url = f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY}"
response = requests.get(url)
models = response.json().get('models', [])
for m in models:
    if 'gemini-1.5' in m.get('name', ''):
        print(m.get('name'))
