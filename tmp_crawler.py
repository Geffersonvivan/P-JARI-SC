import requests
from urllib.parse import urljoin, urlparse
import sys
import re

BASE_URL = "https://www.pjarisc.com.br/"
DOMAIN = "www.pjarisc.com.br"
DOMAIN_ALT = "pjarisc.com.br"

visited = set()
to_visit = [BASE_URL]
results = {}

print("Iniciando varredura...")

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
}

while to_visit and len(visited) < 500:
    current_url = to_visit.pop(0)
    
    if current_url in visited:
        continue
        
    visited.add(current_url)
    
    try:
        response = requests.get(current_url, headers=headers, stream=True, timeout=10)
        status_code = response.status_code
        results[current_url] = status_code
        
        content_type = response.headers.get('Content-Type', '')
        if status_code == 200 and 'text/html' in content_type:
            text = response.raw.read(2000000, decode_content=True).decode('utf-8', errors='ignore')
            hrefs = re.findall(r'<a[^>]+href=["\'](.*?)["\']', text, re.IGNORECASE)
            
            for href in hrefs:
                if not href or href.startswith('javascript:') or href.startswith('mailto:') or href.startswith('tel:'):
                    continue
                    
                full_url = urljoin(current_url, href)
                full_url = full_url.split('#')[0]
                
                parsed_url = urlparse(full_url)
                if (parsed_url.netloc == DOMAIN or parsed_url.netloc == DOMAIN_ALT) and parsed_url.scheme in ['http', 'https']:
                    if full_url not in visited and full_url not in to_visit:
                        to_visit.append(full_url)
                        
    except Exception as e:
        results[current_url] = str(e)

print(f"Varredura concluida. {len(results)} URLs testadas.")
print("=== RESULTADOS ===")

with open('crawler_results.txt', 'w') as f:
    for url, status in sorted(results.items()):
        line = f"{status} - {url}"
        print(line)
        f.write(line + '\n')
