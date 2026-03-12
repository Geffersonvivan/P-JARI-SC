import sys
try:
    import PyPDF2
    with open('Analisar/Consolidado_100629_2022_compressed.pdf', 'rb') as f:
        reader = PyPDF2.PdfReader(f)
        text = ''
        for i in range(min(5, len(reader.pages))): # read first 5 pages
            text += reader.pages[i].extract_text() + '\n'
        print(text[:2500])
except Exception as e:
    import pypdf
    with open('Analisar/Consolidado_100629_2022_compressed.pdf', 'rb') as f:
        reader = pypdf.PdfReader(f)
        text = ''
        for i in range(min(5, len(reader.pages))): 
            text += reader.pages[i].extract_text() + '\n'
        print(text[:2500])
