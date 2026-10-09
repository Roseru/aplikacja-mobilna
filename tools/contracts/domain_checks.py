"""Kontrole semantyki fixture'ów domeny. Nie wykonuje zapisów serwera."""
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo


def check_domain(value, definition):
    errors = []
    if definition == 'ProfileRead' and value['profile'] is not None:
        return check_domain(value['profile']['payload'], 'Profile')
    if definition in {'GoalRecord', 'MealRecord', 'WeightRecord', 'DiaryDayRecord'}:
        return check_domain(value['payload'], definition.removesuffix('Record'))
    if definition in {'GoalPage', 'MealPage', 'WeightPage', 'DiaryDayPage'}:
        return [e for row in value['items'] for e in check_domain(row, definition.removesuffix('Page') + 'Record')]
    if definition in {'Meal', 'Weight'}:
        local = datetime.fromisoformat(value['occurred_at']).astimezone(ZoneInfo(value['time_zone'])).date()
        if local.isoformat() != value['local_date']:
            errors.append('local_date_mismatch')
    if definition == 'Meal':
        ids = [item['item_id'] for item in value['items']]
        if len(ids) != len(set(ids)):
            errors.append('duplicate_item')
        for item in value['items']:
            errors.extend(check_domain(item, 'MealItem'))
    if definition in {'MealItem', 'ProductDraft'}:
        density = value['density_g_per_ml']
        source = value['density_source']
        if (density is None) != (source is None):
            errors.append('density_source_required')
        quantity = value.get('quantity', value.get('package_quantity'))
        if quantity and quantity['unit'] != value['basis_unit'] and density is None:
            errors.append('density_required')
        if quantity and Decimal(quantity['amount']) > 10000:
            errors.append('quantity_range')
    if definition == 'MealItem' and value['nutrition_origin'] == 'catalog_snapshot' and value['product'] is None:
        errors.append('product_reference_required')
    if definition in {'Profile', 'EstimateInput'} and value['height_cm'] is not None:
        if not 0 < Decimal(value['height_cm']) <= 300:
            errors.append('height_range')
    if definition in {'Weight', 'EstimateInput'}:
        if not 0 < Decimal(value['weight_kg']) <= 1000:
            errors.append('weight_range')
    if definition == 'EstimateInput':
        s = Decimal(5 if value['equation_variant'] == 'plus_5' else -161)
        resting = 10 * Decimal(value['weight_kg']) + Decimal('6.25') * Decimal(value['height_cm']) - 5 * value['age_years'] + s
        if resting <= 0:
            errors.append('nonpositive_estimate')
    if definition == 'Goal':
        if Decimal(value['energy_kcal']) > 20000:
            errors.append('goal_range')
        for key in ('protein_g', 'fat_g', 'carbs_g'):
            if value[key] is not None and Decimal(value[key]) > 5000:
                errors.append('goal_range')
        if (value['reason'] == 'history_correction') != (value['correction_of'] is not None):
            errors.append('correction_reference')
        if value['reason'] == 'user_decision':
            decided = datetime.fromisoformat(value['decided_at']).astimezone(ZoneInfo(value['time_zone'])).date()
            if value['effective_from'] < decided.isoformat():
                errors.append('goal_effective_date')
        if value['estimate'] is not None:
            errors.extend(check_domain(value['estimate'], 'Estimate'))
    if definition == 'Estimate':
        errors.extend(check_domain(value['input'], 'EstimateInput'))
        data = value['input']
        pal = {'stationary': '1.5', 'line': '1.8', 'commando': '2.2'}[data['activity_class']]
        s = Decimal(5 if data['equation_variant'] == 'plus_5' else -161)
        resting = 10 * Decimal(data['weight_kg']) + Decimal('6.25') * Decimal(data['height_cm']) - 5 * data['age_years'] + s
        if value['pal'] != pal or Decimal(value['resting_kcal']) != resting or Decimal(value['maintenance_kcal']) != resting * Decimal(pal):
            errors.append('estimate_mismatch')
    return errors
