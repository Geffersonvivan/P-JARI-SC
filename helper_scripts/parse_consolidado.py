import os
try:
    import pypdf
    with open('Analisar/Consolidado_100629_2022_compressed.pdf', 'rb') as f:
        reader = pypdf.PdfReader(f)
        text = ''
        for i in range(min(5, len(reader.pages))): 
            text += reader.pages[i].extract_text() + '\n'
        print("--- EXTRACTED TEXT ---")
        print(text[:4000])
except Exception as e:
    print(f"Error: {e}")
