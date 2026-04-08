import os
import django
from django.urls import URLPattern, URLResolver
from django.conf import settings
import requests

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from config.urls import urlpatterns

def get_urls(patterns, prefix=""):
    urls = []
    for pattern in patterns:
        if isinstance(pattern, URLPattern):
            urls.append(prefix + str(pattern.pattern))
        elif isinstance(pattern, URLResolver):
            urls.extend(get_urls(pattern.url_patterns, prefix + str(pattern.pattern)))
    return urls

all_urls = get_urls(urlpatterns)
results = {}
base = "https://www.pjarisc.com.br"

urls_to_check = [u for u in sorted(set(all_urls)) if '<' not in u and not u.startswith('admin/')]

# We'll also add those initial links we found
urls_to_check.append('privacidade.html')
urls_to_check.append('termos.html')

for u in urls_to_check:
    full_url = f"{base}/{u}" if not u.startswith('http') else u
    try:
        r = requests.get(full_url, timeout=5, allow_redirects=False)
        results[full_url] = r.status_code
    except Exception as e:
        results[full_url] = str(e)

print("=== CHECK_RESULTS ===")
for url, status in sorted(results.items()):
    print(f"{status} - {url}")
