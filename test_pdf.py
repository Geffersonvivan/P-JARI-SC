import fitz
import glob
print("Starting...")
pdfs = glob.glob('uploads/*.pdf')
for count, pdf in enumerate(pdfs):
    if count > 5: break
    try:
        doc = fitz.open(pdf)
        text = doc[0].get_text("text")
        if len(doc) > 1: text += "\n" + doc[1].get_text("text")
        lines = text.split('\n')
        for i, line in enumerate(lines):
            if "BASE LEGAL" in line.upper() or "DESCRIÇÃO DA INFRAÇÃO" in line.upper():
                print(f"[{pdf}] MATCH L{i}: {line.strip()}")
                for j in range(-2, 12):
                    try:
                        print(f"  {j}: {lines[i+j].strip()}")
                    except: pass
                print("---")
                break
    except Exception as e:
        print(f"Error {pdf}: {e}")
