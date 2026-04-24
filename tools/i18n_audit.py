#!/usr/bin/env python3
from __future__ import annotations
import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / 'app/services/translations.py'
TEMPLATE_DIR = ROOT / 'app/templates'
AR_RE = re.compile(r'[\u0600-\u06FF]')

def load_catalog():
    text = CATALOG_PATH.read_text(encoding='utf-8')
    raw = text.split('AR_TO_EN = ', 1)[1].split('\n\nTRANSLATIONS', 1)[0]
    return ast.literal_eval(raw)

def safe_replace(text, source, target):
    if not source or source not in text:
        return text
    if re.fullmatch(r'[\u0600-\u06FF]+', source):
        return re.sub(r'(?<![\u0600-\u06FF])' + re.escape(source) + r'(?![\u0600-\u06FF])', target, text)
    return text.replace(source, target)

def translate_preview(text, catalog):
    out = text
    for source, target in sorted(catalog.items(), key=lambda item: len(item[0]), reverse=True):
        out = safe_replace(out, source, target)
    return out

def strip_known_conditionals(text):
    text = re.sub(r"{{\s*'[^']*[A-Za-z][^']*'\s+if\s+is_en\s+else\s+'[^']*[\u0600-\u06FF][^']*'\s*}}", '', text)
    text = re.sub(r"{{\s*'[^']*[\u0600-\u06FF][^']*'\s+if\s+[^}]*?else\s+'[^']*[A-Za-z][^']*'\s*}}", '', text)
    text = re.sub(r"\('([^']*[A-Za-z][^']*)'\s+if\s+is_en\s+else\s+'([^']*[\u0600-\u06FF][^']*)'\)", '', text)
    text = re.sub(r'data-ar="[^"]*[\u0600-\u06FF][^"]*"\s+data-en="[^"]*"', '', text)
    text = re.sub(r"{%\s*if\s+(?:ui_lang|\(ui_lang or 'ar'\))[^%]*==\s*'en'\s*%}(.*?){%\s*else\s*%}.*?{%\s*endif\s*%}", r"\1", text, flags=re.DOTALL)
    return text

def main():
    catalog = load_catalog()
    findings = []
    for path in TEMPLATE_DIR.glob('*.html'):
        source = strip_known_conditionals(path.read_text(encoding='utf-8', errors='ignore'))
        translated = translate_preview(source, catalog)
        if AR_RE.search(translated):
            snippets = []
            for match in re.finditer(r'.{0,50}[\u0600-\u06FF].{0,80}', translated):
                snippet = re.sub(r'\s+', ' ', match.group(0)).strip()
                if snippet not in snippets:
                    snippets.append(snippet)
                if len(snippets) >= 5:
                    break
            findings.append((path.relative_to(ROOT), len(AR_RE.findall(translated)), snippets))
    print(f'Catalog entries: {len(catalog)}')
    print(f'Templates with possible untranslated legacy Arabic: {len(findings)}')
    for path, count, snippets in sorted(findings, key=lambda item: -item[1]):
        print(f'\n{path} ({count})')
        for snippet in snippets:
            print('  -', snippet)

if __name__ == '__main__':
    main()
