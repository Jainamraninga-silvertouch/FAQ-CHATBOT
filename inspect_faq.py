from app.services.parser import extract_text
from pathlib import Path
for path in [Path('upload/BatchSmart_FAQs.xlsx'), Path('upload/LabelSmart_FAQs.xlsx')]:
    text = extract_text(path.read_bytes(), path.name)
    print('===', path.name, '===')
    print(text[:10000])
    print('\n')
