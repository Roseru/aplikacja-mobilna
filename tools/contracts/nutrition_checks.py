"""Referencyjna arytmetyka kontraktu E0; tylko uruchomienie wektorów."""
from decimal import Decimal, ROUND_HALF_UP, localcontext

FIELDS = ('energy_kcal', 'protein_g', 'fat_g', 'carbs_g')


def canonical(value):
    result = format(value, 'f')
    return result.rstrip('0').rstrip('.') if '.' in result else result


def calculate(items):
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_UP
        sums = {key: Decimal(0) for key in FIELDS}
        missing = {key: 0 for key in FIELDS}
        for item in items:
            amount = Decimal(item['amount'])
            if not amount.is_finite() or not 0 < amount <= 10000:
                raise ValueError('quantity_range')
            if item['unit'] != item['basis_unit']:
                density = item.get('density_g_per_ml')
                if density is None:
                    raise ValueError('density_required')
                density = Decimal(density)
                if density <= 0:
                    raise ValueError('density_range')
                if item['unit'] == 'ml':
                    amount *= density
                else:
                    amount = (amount / density).quantize(Decimal('0.000000000001'))
            for key in FIELDS:
                raw = item['nutrition_per_100'][key]
                if raw is None:
                    missing[key] += 1
                else:
                    sums[key] += Decimal(raw) * amount / Decimal(100)
        return {key: {'known_sum': canonical(sums[key]), 'missing_count': missing[key],
                      'complete': missing[key] == 0,
                      'display': format(sums[key].quantize(Decimal('1') if key == 'energy_kcal' else Decimal('0.1')), 'f')}
                for key in FIELDS}


def verify_vectors(path):
    import json
    vectors = json.loads(path.read_text(encoding='utf-8'))
    assert vectors['formula_version'] == 'nutrition_v1'
    ids = set()
    for vector in vectors['cases']:
        assert vector['id'] not in ids, vector['id']
        ids.add(vector['id'])
        assert vector['derivation'], vector['id']
        try:
            result = calculate(vector['items'])
        except ValueError as error:
            assert str(error) == vector.get('expected_error'), vector['id']
        else:
            assert 'expected_error' not in vector, vector['id']
            assert result == vector['expected'], f"{vector['id']}: {result} != {vector['expected']}"
    for case in vectors['day_cases']:
        # Zamknięcie doby wpływa na punkty, a nie samą deklarację kompletności.
        complete = (case['declared_complete'] and case['meal_count'] > 0
                    and case['missing_energy_count'] == 0 and Decimal(case['known_energy']) > 0)
        assert complete == case['expected_complete'], case['id']
    return len(vectors['cases']), len(vectors['day_cases'])
