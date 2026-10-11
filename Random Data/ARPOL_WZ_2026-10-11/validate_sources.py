"""Validate research references, units, missing data and preserved PDF hashes."""
import hashlib
import json
from decimal import Decimal
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    data = json.loads((root / 'arpol_wz_sources.json').read_text(encoding='utf-8'))
    manifest = json.loads((root / 'sources/manifest.json').read_text(encoding='utf-8'))
    sources = {s['id']: s for s in manifest['sources']}
    assert len(sources) == len(manifest['sources'])
    cards = {c['id']: c for c in data['product_cards']}
    assert len(cards) == len(data['product_cards'])
    for card in cards.values():
        assert card['source_id'] in sources
        assert card['basis_amount'] == '100' and card['basis_unit'] == 'g'
        assert Decimal(card['net_mass_g']) > 0
        assert card['manufacturer'] is None
        assert card['ration_binding'] == 'candidate_only'
        assert not card['complete_for_ration_import']
        for value in card['source_values'].values():
            assert isinstance(value, str) and Decimal(value.removeprefix('<')) >= 0
        prep = card['preparation']
        if card['nutrition_state'] == 'dry_before_preparation':
            assert prep['status'] == 'source_read' and prep['source_id'] in sources
            assert Decimal(prep['added_water_ml']) > 0
            assert prep['instruction_pl']
    for ration in data['rations']:
        assert ration['source_id'] in sources and not ration['complete']
        assert ration['total_macros'] is None
        for item in ration['components']:
            assert item['occurrence_source_id'] == ration['source_id']
            assert item['exact_product_binding'] == 'unconfirmed'
            assert item['nutrition_for_ration_component'] is None
            assert item['quantity_unit'] in ('g', 'piece')
            assert set(item['candidate_card_ids']) <= cards.keys()
            if item['quantity_unit'] == 'piece':
                assert item['net_mass_g'] is None and item['unit_mass_g'] is None
    for source in sources.values():
        assert source['url'].startswith('https://') and source['checked_on'] == '2026-10-11'
        if source.get('local_file'):
            path = root / 'sources' / source['local_file']
            assert path.read_bytes().startswith(b'%PDF')
            assert hashlib.sha256(path.read_bytes()).hexdigest() == source['body_sha256']
    kisiel = cards['kisiel']
    assert kisiel['source_values']['protein_g'] == '<0.4'
    assert kisiel['source_values']['fat_g'] == '<0.2'
    assert kisiel['source_values']['energy_kcal'] == '493'
    assert kisiel['source_energy_kj'] == '1644'
    assert data['status'] == 'research_sources_not_official_catalog'
    print(f"PASS: {len(data['rations'])} racje, "
          f"{sum(len(r['components']) for r in data['rations'])} wystąpień, "
          f"{len(cards)} kart, {len(sources)} źródeł/prób; PDF SHA-256 zgodne.")


if __name__ == '__main__':
    main()
