"""Join DLA contents to archived COMRAD values using reviewed, explicit aliases.
Preserves source values and flags ambiguity; does not estimate missing nutrients.
"""
from pathlib import Path
import json, re, hashlib
from collections import Counter

ROOT=Path(__file__).resolve().parent.parent
URL='https://www.hprc-online.org/sites/default/files/2026-04/MRE_46_menus_COMRAD.pdf'
data=json.loads((ROOT/'mre_2026.json').read_text(encoding='utf-8'))
rows=json.loads((ROOT/'sources/comrad_2026_raw.json').read_text(encoding='utf-8'))
aliases_text='''Cheese Spread, Cheddar, Plain|Cheese Spread, Cheddar, Plain, 1 ounce
Cheese Spread, Cheddar Plain|Cheese Spread, Cheddar, Plain, 1 ounce
Crackers, Vegetable|Crackers, Vegetable, TFF
Cornbread|Cornbread, TFF
Cheese Filled Crackers, Pepperoni Pizza|Filled Crackers, Cheese and Pepperoni
Fruit Puree Squeeze, Apple, Strawberry, and Carrot|Fruit Puree Squeeze, Apple, Strawberry and Carrot
Trail Mix, Recovery with Pretzels|Recovery Trail Mix, Pretzel
Trail Mix, Recovery, with Pretzels|Recovery Trail Mix, Pretzel
Filled Bakery Item, Cinnamon Bun|Filled Bakery, Cinnamon Bun, High Oleic
Chocolate Protein Drink Powder, Chocolate|Chocolate Protein Drink
Chicken, Egg Noodles, and Vegetables, in Sauce|Chicken, Noodles and Vegetables in Sauce
Applesauce, with Raspberry Puree|Fruits, Wet Pack, Applesauce, Raspberry
Crackers, Plain|Crackers, Plain, TFF
Peanut Butter, Chunky/Crunchy|Peanut Butter, Chunky, 1 ounce
Beverage Powder, Carbohydrate, Fortified and Enhanced|Beverage Base, Carbohydrate Fortified, Formulation D
Spaghetti with Beef and Sauce|Spaghetti with Beef and Sauce, High Energy
Snack Bread, Italian Bread Sticks|Italian Bread Sticks, TFF
Fruit, Dried Cranberries, Sliced|Dried Fruit, Cranberries
Beverage Bases (Powdered), Sweetened with Non-Nutritive Sweetener, Not Fortified|Beverage Base, Sugar Free
Chewing Gum, with Caffeine|Chewing Gum, Caffeinated (1 piece)
Chicken Chunks, White, Cooked|Chicken Chunks, White, 5 oz
Fruit Mix, Apples, Blueberries and Cherries|Dried Fruit Mix, Apples, Blueberries and Cherries
Tortillas, Plain|Tortilla, Plain, TFF
Tortilla, Plain|Tortilla, Plain, TFF
Meat Snack, Sticks, Teriyaki|Beef Snack, Teriyaki Stick
Santa Fe Style Brown Rice and Beans|Santa Fe Rice and Beans, Brown Rice
Tortillas, Whole Grain|Tortilla, Whole Grain
Nut and Fruit Mix, Nuts and Raisins with Pan Coated Chocolate Disks|Nut and Raisin Mix with Pan Coated Chocolate Disks
Beverage Bases, Sweetened with Non-nutritive Sweetener, Fortified, Orange|Beverage Base, Sugar Free, Orange with Vitamin C and Ca
Beef Strips in a Savory Tomato Sauce|Beef Strips in a Savory Tomato Based Sauce
Peanut Butter Smooth|Peanut Butter, Smooth, 1 ounce
Peanut Butter, Smooth|Peanut Butter, Smooth, 1 ounce
Snack Bread, White Wheat|Snack Bread, White Whole Wheat, TFF
Preserves, Blackberry|Jam, Blackberry
Fruit and Vegetable Blend Juice Smoothie Powder, Tropical Blend|Fruit and Vegetable Blend Juice Smoothie
Cobbler, Cherry Blueberry|Cobbler, Cherry Blueberry, TFF
Oatmeal Cookie, Chocolate Chunk|Cookie, Oatmeal Chocolate Chunk, High Oleic
Cheese Spread, Cheddar, with Jalapeno Peppers|Cheese Spread, Cheddar with Jalapeno Peppers, 1 ounce
Snack Bread, Multigrain|Snack Bread, Multigrain, TFF
Spice Blend, Powdered Hot Sauce Seasoning|Hot Sauce, Powdered, Texas Pete Style
Spice Blends, Powdered Hot Sauce Seasoning|Hot Sauce, Powdered, Texas Pete Style
Caffeinated Chewables, Lime|Energy Chew, Stingerita Lime
Pizza Slice, Cheese|Cheese Pizza
Applesauce, Carbohydrate Enhanced|Fruits, Wet Pack, Applesauce, Carbohydrate Enhanced
Jalapeno Cashews|Nuts, Cashews, Jalapeno (38 grams)
Spice, Crushed Red Pepper|Red Pepper, Crushed
Elbow Macaroni in Tomato Sauce|Elbow Macaroni in a Tomato Sauce
Recovery Bar, Salted Caramel|Recovery Bar, Salted Caramel Marshmallow Crisp
Applesauce, with Mango and Peach Puree|Fruits, Wet Pack, Applesauce, Mango Peach
Peanut Butter, Smooth, Chocolate|Peanut Spread, Chocolate, 1 ounce
Preserves, Strawberry|Jam, Strawberry
Beverage Powder, Carbohydrate Electrolytes|Beverage Powder, Carbohydrate Electrolyte
Swirl Roll, Italian Style Herb and Cheese|Italian Style Herb and Cheese Swirl Roll
Mexican Style Rice and Bean Bowl|Mexican Rice and Bean Bowl
Peanut Butter Bites, Cocoa|Peanut Butter Bites, Chocolate
Pretzels, Nuggets, Honey Mustard and Onion|Pretzels, Nibs, Honey Mustard and Onion
Filled Pretzels, Cheddar Cheese|Filled Pretzels, Cheddar
Nut Bar, Almond and Coconut|Almond and Coconut Bar, (Kind bar)
Chicken Burrito Bowl|Chicken Burrito Bowl, Brown Rice
Muffin Top, Maple, Whole Grain|Maple Muffin Top, Whole Grain, High Oleic
Peanuts, Dry Roasted, Salted|Nuts, Peanuts, Dry Roasted
Pan Coated Candy, Disks, Milk Chocolate, Plain|Pan Coated Chocolate Disks, Plain
Thai Style Curry with Chicken, Brown Rice, and Vegetables|Thai Style Red Curry Chicken with Brown Rice and Vegetables
Granola with Milk, Apples, and Cinnamon|Granola with Milk, Apples and Cinnamon
Pan Coated Candy, Oval/Round, Milk Chocolate with Peanuts|Pan Coated Chocolate Disks, Peanut
Italian Sausage with Peppers and Onions in Marinara Sauce|Italian Style Pork Sausage with Peppers and Onions in Marinara Sauce
Toasted Pastry, Chocolate Chip|Toaster Pastry, Chocolate Chip
Cheese Spread, Cheddar with Bacon|Cheese Spread, Cheddar with Bacon, 1 ounce
Almonds, Smoked|Nuts, Almonds, Smoked
Tuna, Chunk, Light, Lemon Pepper|Tuna, Chunk Light, Lemon Pepper
Dessert Spread, Apple Pie|Apple Pie Dessert Spread
Baked Snack Crackers, Cheddar|Baked Snack Crackers, Cheddar Cheese
Pan Coated Candy, Disks, Peanut Butter, Plain|Pan Coated Disks, Peanut Butter
Sugar Cookies, Patriotic|Cookie, Sugar, Patriotic, TFF
Pizza Slice, Pepperoni|Pizza, Pepperoni
Apple Pieces in Spiced Sauce|Spiced Apples
Oatmeal Cookie, Plain|Cookie, Oatmeal, High Oleic
Southwest Style Beef and Black Beans with Sauce|Southwest Beef and Black Beans
Tortillas, Chipotle|Tortilla, Chipotle, TFF
Coffee|Coffee, Soluble, Freeze Dried
Creamer|Creamer, Non-Dairy, Dry
Sugar Substitute|Sucralose'''
aliases=dict(line.split('|') for line in aliases_text.splitlines())

profiles={}
for row in rows:
    if row['record_type']!='component':continue
    signature=json.dumps([row['name_source'],row['values_per_source_portion']],sort_keys=True)
    pid='N'+hashlib.sha256(signature.encode()).hexdigest()[:10]
    row['nutrition_profile_id']=pid
    if pid in profiles:
        profiles[pid]['source_menu_numbers'].append(row['menu_number'])
        continue
    v=row['values_per_source_portion']
    flags=[]
    if 'Caffeinated (1 piece)' in row['name_source']:
        flags.append('COMRAD podaje różne wartości i masy dla tej samej nazwy gumy w różnych menu oraz 0 mg kofeiny w części wierszy. Zachowano dane źródłowe; wymagają weryfikacji z etykietą.')
    if all(v[k] is not None for k in ['protein_g','carbohydrate_g','fat_g','energy_kcal']) and v['energy_kcal']>20:
        calc=4*v['protein_g']+4*v['carbohydrate_g']+9*v['fat_g']
        if abs(calc-v['energy_kcal'])/v['energy_kcal']>.25:
            flags.append('Kontrola orientacyjna 4/4/9 różni się od podanych kcal o ponad 25%. Nie poprawiano liczby źródłowej; wymaga weryfikacji.')
    if v['sugars_g'] is not None and v['carbohydrate_g'] is not None and v['sugars_g']>v['carbohydrate_g']+.1:
        flags.append('W źródle cukry przekraczają węglowodany ogółem; wymaga weryfikacji.')
    profiles[pid]={'id':pid,'name_source':row['name_source'],'basis':'per_source_portion','values':v,
        'source_url':URL,'source_file':'sources/HPRC_COMRAD_MRE_46_2026.pdf','source_page':row['source_page'],
        'source_menu_numbers':[row['menu_number']],'quality_notes_pl':flags}

def find_profiles(name,menu):
    rs=[r for r in rows if r['record_type']=='component' and r['name_source']==name]
    local=[r for r in rs if r['menu_number']==menu]
    selected=local or rs
    return list(dict.fromkeys(r['nutrition_profile_id'] for r in selected)), bool(local)

def attach(item, menu):
    name=item['name_en']; kind=item.get('kind','food_or_beverage')
    note=[]
    item['nutrition']={'status':'not_available','profile_ids':[],'notes_pl':note}
    if kind in ['equipment','packaging'] or name in ['Hand & Body Wipe','Toilet Tissue','Safety Matches']:
        item['nutrition']['status']='not_applicable';return
    if name=='Accessory Packet A':
        item['nutrition']['status']='see_packet_components';return
    if name=='Accessory Packet B':
        ids,local=find_profiles('Group Average - MRE 42, Accessory Packet B',menu)
        item['nutrition'].update(status='source_packet_average',profile_ids=ids)
        note.append('COMRAD 2026 wykorzystuje średnią opisaną jako MRE 42, Accessory Packet B. Przypis mówi, że kalorie pochodzą z gumy. Nie dodawać tej średniej ponownie do rozpisanych składników pakietu.')
        return
    if name in ['Salt','Chewing Gum, without Caffeine']:
        note.append('COMRAD nie podaje osobnego profilu tego składnika. Dla pakietu B podaje wyłącznie średnią zbiorczą. Braku nie zastąpiono zerem.')
        return
    if name=='Cake':
        names=['Pound Cake, Vanilla, High Oleic','Pound Cake, Marble, High Oleic','Pound Cake, Applesauce, High Oleic']
        ids=[find_profiles(n,menu)[0][0] for n in names]
        item['nutrition'].update(status='variant_profiles',profile_ids=ids)
        note.append('Trzy alternatywne smaki z przypisu DLA; wybrać jeden, nie sumować.')
        return
    if name=='Beverage Powder, Carbohydrate, Enhanced with Caffeine':
        names=['Beverage, Lemon-Lime, Caffeinated','Beverage, Mixed Berry, Caffeinated']
        item['nutrition'].update(status='variant_profiles',profile_ids=[find_profiles(n,menu)[0][0] for n in names])
        note.append('Dwa alternatywne smaki z przypisu DLA; wybrać jeden, nie sumować.')
        return
    if name=='Pan Coated Candy, Disks, Fruit Flavored, Original':
        ids,_=find_profiles('Pan Coated Fruit Flavored Disks, Berry',menu)
        item['nutrition'].update(status='different_variant_reference_only',reference_profile_ids=ids)
        note.append('DLA: Original; COMRAD w menu 3: Berry. Profil Berry jest wyłącznie porównaniem, nie potwierdzonym profilem Original.')
        return
    if name in ['Spice Blend, Picante Seasoning','Spice Blends, Picante Seasoning']:
        ids,_=find_profiles('Hot Sauce, Powdered (Tapatio)',menu)
        item['nutrition'].update(status='unconfirmed_equivalence_reference_only',reference_profile_ids=ids)
        note.append('DLA: Picante Seasoning; COMRAD w tym menu: Hot Sauce, Powdered (Tapatio). Nie potwierdzono tożsamości produktów. COMRAD podaje tylko masę, kcal i sód; brak makro.')
        return
    target=aliases.get(name,name)
    ids,local=find_profiles(target,menu)
    if ids:
        item['nutrition'].update(status='source_profile' if local else 'source_profile_other_menu',profile_ids=ids)
        if target!=name:note.append('Dopasowanie nazw DLA/COMRAD: '+target+'.')
        if not local:note.append('Profil tej samej nazwanej pozycji pobrano z innego menu COMRAD 2026; nie jest potwierdzeniem konkretnej partii.')
        if item.get('footnote_id') in ['1','2','3']:
            item['nutrition']['status']='source_generic_profile'
            note.append('COMRAD podaje profil ogólny tej rodziny napoju, bez odrębnych danych dla wszystkich smaków z przypisu DLA.')
        if name=='Toasted Pastry, Chocolate Chip':
            note.append('W menu 20 COMRAD występuje Chocolate Fudge, a w DLA Chocolate Chip. Użyto profilu Chocolate Chip z menu 16; nie zamieniono smaku w zawartości DLA.')
    else:
        note.append('Nie znaleziono potwierdzonego dopasowania w COMRAD 2026.')

for m in data['menus']:
    for item in m['components']:attach(item,m['menu_number'])
    total=next(r for r in rows if r['menu_number']==m['menu_number'] and r['record_type']=='menu_total')
    # Source totals are archived, never silently used as sums of DLA components.
    m['comrad_reported_total']={'values':total['values_per_source_portion'],'source_url':URL,'source_page':total['source_page'],
        'note_pl':'Suma opublikowana w COMRAD, nie obliczona z listy DLA. Może nie odpowiadać wariantom i dodatkom z DLA ani sumie wierszy źródłowych.'}
for packet in data['accessory_packets'].values():
    for item in packet['components']:attach(item,1)

data['schema_version']='1.1'
data['nutrition_source']={'url':URL,'landing_page':'https://www.hprc-online.org/nutrition/comrad','local_file':'sources/HPRC_COMRAD_MRE_46_2026.pdf',
    'basis_pl':'Wartości na porcję o masie weight_g określonej w COMRAD. Nie na 100 g i nie obietnica masy każdej produkowanej saszetki.',
    'blank_cells':'null = brak danych w źródle; 0 = zero podane przez źródło.',
    'unit_caveats_pl':['Selenium: źródło ma nagłówek Sel (mg), ale jednostka jest podejrzana. Zapisano jako selenium_source_unit, bez automatycznej interpretacji lub przeliczenia.','Linoleic Acid i Alphalinolenic Acid: brak jednostki w nagłówku PDF; zapisano jako *_source_unit bez domyślnego przypisania gramów.']}
data['nutrition_profiles']=profiles
data['limitations_pl']=[s for s in data['limitations_pl'] if not s.startswith('Tabela menu nie podaje')]
data['limitations_pl'] += ['Gramatury i wartości odżywcze pochodzą z COMRAD, a zawartość menu z DLA; różnice źródeł opisano przy produktach.',
    'Quantity=null to brak liczby sztuk. Masa porcji COMRAD jest w profilu odżywczym jako weight_g.',
    'Nie należy sumować wszystkich profili alternatywnych ani traktować profili porównawczych jako potwierdzonego dopasowania.']
(ROOT/'mre_2026.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(ROOT/'sources/nutrition_name_mapping.json').write_text(json.dumps(aliases,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Profiles:',len(profiles))
print('Component status:',dict(Counter(i['nutrition']['status'] for m in data['menus'] for i in m['components'])))
print('Not available:',[i['name_en'] for m in data['menus'] for i in m['components'] if i['nutrition']['status']=='not_available'])
