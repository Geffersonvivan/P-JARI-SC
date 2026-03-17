import re

with open('templates/home.html', 'r', encoding='utf-8') as f:
    html = f.read()

scripts = re.findall(r'<script>(.*?)</script>', html, re.DOTALL)
for i, script in enumerate(scripts):
    c_brace = 0
    c_paren = 0
    in_string = False
    string_char = ''
    escape = False
    
    for line_num, line in enumerate(script.split('\n')):
        for char in line:
            if escape:
                escape = False
                continue
            if char == '\\':
                escape = True
                continue
            
            if not in_string:
                if char in "'\"`":
                    in_string = True
                    string_char = char
                elif char == '{': c_brace += 1
                elif char == '}': c_brace -= 1
                elif char == '(': c_paren += 1
                elif char == ')': c_paren -= 1
            else:
                if char == string_char:
                    # check for `rawHtml += \` ... </div>\`;` which has interpolation
                    in_string = False
                    
    print(f"Script {i}: Braces delta = {c_brace}, Parens delta = {c_paren}")

