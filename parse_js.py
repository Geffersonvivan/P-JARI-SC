import re
import sys

def check_returns():
    with open('templates/home.html', 'r', encoding='utf-8') as f:
        lines = f.readlines()

    in_script = False
    stack = 0 # tracking function scope {}
    in_function = False
    function_stack = []

    for i, line in enumerate(lines):
        line_num = i + 1
        
        if '<script' in line:
            in_script = True
            stack = 0
            in_function = False
            function_stack = []
            continue
            
        if '</script>' in line:
            in_script = False
            continue
            
        if not in_script:
            continue
            
        # Very rough parsing to find top-level returns
        
        # Check for function declarations
        if re.search(r'function\s*[\w\s]*\(', line) or re.search(r'\w+\s*=\s*function', line) or re.search(r'\([^)]*\)\s*=>', line) or re.search(r'async\s+function', line):
            # This is flawed but gets us closer
            # We will use esprima via python context if needed, or simple regex
            pass

    # Let's just find all returns and print them
    in_script = False
    for i, line in enumerate(lines):
        if '<script' in line: in_script = True
        elif '</script>' in line: in_script = False
        elif in_script:
            if re.search(r'\breturn\b', line):
                print(f"Line {i+1}: {line.strip()}")

check_returns()
