"""Rasterize a locally exported acceptance PDF; never modifies the source."""
import argparse
import json
from pathlib import Path
import pypdfium2 as pdfium

parser = argparse.ArgumentParser()
parser.add_argument('pdf', type=Path)
parser.add_argument('output', type=Path)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
with pdfium.PdfDocument(str(args.pdf)) as document:
    pages = []
    for number, page in enumerate(document, 1):
        image = args.output / f'page-{number}.png'
        page.render(scale=1.5).to_pil().save(image)
        pages.append({'page': number, 'image': str(image), 'text': page.get_textpage().get_text_range()})
    print(json.dumps({'page_count': len(document), 'pages': pages}, ensure_ascii=False, indent=2))
