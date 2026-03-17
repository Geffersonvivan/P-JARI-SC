import esprima
import re

with open('templates/home.html', 'r', encoding='utf-8') as f:
    html = f.read()

scripts = re.findall(r'<script>(.*?)</script>', html, re.DOTALL)
for i, script in enumerate(scripts):
    print(f"Linting script {i}...")
    # remove django tags that might break JS parsing
    clean_script = re.sub(r'\{%[^%]*%\}', '', script)
    # replace django variables with safe string "x"
    clean_script = re.sub(r'\{\{[^\}]*\}\}', '"x"', clean_script)
    
    try:
        esprima.parseScript(clean_script)
        print(f"Script {i} is OK")
    except Exception as e:
        print(f"Script {i} ERROR: {e}")
