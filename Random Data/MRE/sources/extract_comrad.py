"""Extract the numeric columns of the archived COMRAD PDF without shifting blanks.
Run with Python + pdfplumber from any directory. Outputs comrad_2026_raw.json.
This parser is specific to the archived four-page MRE 46 document.
"""
from pathlib import Path
import json
import re
import pdfplumber

ROOT = Path(__file__).resolve().parent
FIELDS = [
    ('weight_g', 138.98), ('energy_kcal', 154.22), ('protein_g', 169.46),
    ('carbohydrate_g', 184.70), ('fiber_g', 199.94), ('fat_g', 215.18),
    ('trans_fat_g', 230.42), ('cholesterol_mg', 245.66), ('vitamin_a_iu', 268.58),
    ('thiamin_b1_mg', 283.82), ('riboflavin_b2_mg', 299.06), ('niacin_b3_mg', 314.30),
    ('vitamin_b6_mg', 329.54), ('vitamin_b12_mcg', 344.78), ('vitamin_c_mg', 360.74),
    ('vitamin_d_mcg', 378.02), ('vitamin_e_mg', 393.26), ('folate_mcg', 412.82),
    ('vitamin_k_mcg', 430.10), ('calcium_mg', 450.62), ('fluoride_mg', 466.94),
    ('iodine_mcg', 486.62), ('iron_mg', 501.86), ('magnesium_mg', 517.10),
    ('phosphorus_mg', 533.30), ('potassium_mg', 557.30), ('selenium_source_unit', 570.86),
    ('sodium_mg', 587.06), ('zinc_mg', 602.30), ('monounsaturated_fat_g', 621.98),
    ('polyunsaturated_fat_g', 639.86), ('saturated_fat_g', 655.82),
    ('linoleic_acid_source_unit', 676.34), ('alpha_linolenic_acid_source_unit', 706.94),
    ('sugars_g', 722.54), ('caffeine_mg', 737.78),
]

def extract():
    result = []
    menu = None
    with pdfplumber.open(ROOT / 'HPRC_COMRAD_MRE_46_2026.pdf') as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            for line in page.extract_text_lines():
                text = line['text']
                match = re.match(r'MENU (\d+)\b', text)
                if match:
                    menu = int(match.group(1))
                    continue
                if menu is None or text.startswith(('Item ', 'Weight ', 'NSOR', '% NSOR', 'Ration ', '*ACCESSORY')):
                    continue
                # Crop each visual row to retain cell coordinates and blank cells.
                words = page.crop((0, line['top'] - .1, page.width, line['bottom'] + .1)).extract_words(x_tolerance=.1, y_tolerance=.1)
                name = ' '.join(w['text'] for w in words if w['x0'] < 125)
                values = dict.fromkeys(k for k, _ in FIELDS)
                found = 0
                for word in words:
                    if word['x0'] < 125:
                        continue
                    if not re.fullmatch(r'\d+(?:\.\d+)?', word['text']):
                        raise ValueError(f'Unexpected numeric cell on page {page_no}: {word}')
                    key, edge = min(FIELDS, key=lambda f: abs(f[1] - word['x1']))
                    if abs(edge - word['x1']) > .6:
                        raise ValueError(f'Unrecognized column on page {page_no}: {word}')
                    if values[key] is not None:
                        raise ValueError(f'Duplicate cell {key}: {name}')
                    values[key] = float(word['text'])
                    found += 1
                if not found:
                    continue
                result.append({'menu_number': menu, 'source_page': page_no, 'name_source': name,
                               'record_type': 'menu_total' if name == 'Total' else 'component',
                               'values_per_source_portion': values})
    assert {r['menu_number'] for r in result} == set(range(1,25))
    assert sum(r['record_type'] == 'menu_total' for r in result) == 24
    (ROOT / 'comrad_2026_raw.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result

if __name__ == '__main__':
    rows = extract()
    for number in range(1,25):
        print('MENU', number)
        for row in rows:
            if row['menu_number'] == number:
                v = row['values_per_source_portion']
                print(row['name_source'], {k:v[k] for k in ['weight_g','energy_kcal','protein_g','carbohydrate_g','fat_g']})
