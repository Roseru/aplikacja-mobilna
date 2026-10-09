"""Audyt niezmienionej próbki i normalizacji; nie certyfikuje etykiet."""
import json
from decimal import Decimal, ROUND_HALF_UP, localcontext


def verify_source(source_path, package):
    source = json.loads(source_path.read_text(encoding='utf-8'), parse_float=Decimal)
    rows = [p for group in source['posilki'] for p in group['produkty']] + source['dodatki_spozywcze']
    assert len(rows) == 22
    assert sum(p['wartosci_odzywcze'] is None for p in rows) == 4
    assert sum(p['jednostka'] == 'szt.' for p in rows) == 3
    assert sum(p['wartosci_odzywcze']['kcal'] for p in rows if p['wartosci_odzywcze']) == 3466
    assert source['wartosci_oszacowane_policzonych_produktow']['kcal'] == 3468
    assert source['deklarowana_energia_kcal'] == 3600
    assert package['kind'] == 'demo' and len(package['products']) == 18
    fields = dict(energy_kcal='kcal', protein_g='bialko_g', fat_g='tluszcz_g', carbs_g='weglowodany_g')
    locations = set()
    with localcontext() as context:
        context.prec = 50
        for product in package['products']:
            locator = product['source_locator']
            assert locator not in locations
            locations.add(locator)
            row = source
            for part in locator.split('/')[1:]:
                row = row[int(part)] if isinstance(row, list) else row[part]
            assert row['jednostka'] == product['basis_unit'] == product['package_quantity']['unit'] == 'g'
            assert Decimal(row['ilosc']) == Decimal(product['package_quantity']['amount'])
            for target, original in fields.items():
                normalized = (Decimal(row['wartosci_odzywcze'][original]) * 100 / Decimal(row['ilosc'])).quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)
                assert Decimal(product['nutrition_per_100'][target]) == normalized, (locator, target)
    return len(locations) * len(fields)
