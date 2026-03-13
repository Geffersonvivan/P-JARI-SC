from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import os
import time

try:
    options = Options()
    options.add_argument('--headless')
    driver = webdriver.Chrome(options=options)
    
    file_path = f"file://{os.path.abspath('mermaid_test.html')}"
    print(f"Opening: {file_path}")
    driver.get(file_path)
    
    time.sleep(2)
    
    print("Logs:")
    for entry in driver.get_log('browser'):
        print(entry)
        
    driver.quit()
except Exception as e:
    print(f"Error: {e}")
