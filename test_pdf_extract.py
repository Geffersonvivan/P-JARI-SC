import fitz
import sys

def parse_pdf(path):
    print("Parsing:", path)
    doc = fitz.open(path)
    text = ""
    for page in doc:
         text += page.get_text()
    
    lines = text.split('\n')
    found_desc = False
    
    for i, line in enumerate(lines):
        # We look for "DESCRIÇÃO DA INFRAÇÃO"
        # and the actual text might be in the lines immediately following it, or nearby.
        print(f"[{i}] {line}")
        if "DESCRIÇÃO DA INFRAÇÃO" in line.upper():
            print(">>> FOUND 'DESCRIÇÃO DA INFRAÇÃO' at line", i)
            # Print next 5 lines
            for j in range(1, 6):
                if i+j < len(lines):
                    print(f"   + {lines[i+j]}")

if __name__ == '__main__':
    parse_pdf("./media/uploads/Consolidado_80226_2022.pdf")
