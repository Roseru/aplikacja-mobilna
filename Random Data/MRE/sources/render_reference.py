"""Generate readable references from the source-linked JSON dataset."""
from pathlib import Path
import json, hashlib
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
d = json.loads((ROOT/'mre_2026.json').read_text(encoding='utf-8'))
profiles = d['nutrition_profiles']
def fmt(v):
    return '—' if v is None else f'{v:g}'.replace('.', ',')
def save(name, lines):
    (ROOT/name).write_text('\n'.join(lines)+'\n', encoding='utf-8')
keys = ['weight_g','energy_kcal','protein_g','fat_g','carbohydrate_g','fiber_g','sugars_g','sodium_mg']
header = ['| Produkt / wariant | Porcja g | kcal | Białko g | Tłuszcz g | Węglowodany g | Błonnik g | Cukry g | Sód mg | Pełny profil |', '|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
def item_rows(item, notes):
    n = item['nutrition']; name = item.get('name_pl') or item['name_en']
    if name != item['name_en']: name += ' / '+item['name_en']
    ids = n.get('profile_ids', [])
    result=[]
    for pid in ids:
        p=profiles[pid]
        label=name
        if len(ids)>1: label+=' — alternatywa: '+p['name_source']
        if n['status']=='source_packet_average': label+=' (średnia pakietu)'
        if n['status']=='source_generic_profile': label+=' (profil ogólny)'
        result.append('| '+label+' | '+' | '.join(fmt(p['values'][k]) for k in keys)+f' | [Profil](Wartosci_odzywcze_2026.md#{pid.lower()}) |')
    if not ids:
        state={'not_applicable':'Nie dotyczy','see_packet_components':'Rozpiska pakietu poniżej'}.get(n['status'],'Brak potwierdzonych danych')
        result.append('| '+name+' | '+' | '.join(['—']*8)+' | '+state+' |')
    for note in n.get('notes_pl',[]): notes.append(f'**{name}:** {note}')
    for pid in n.get('reference_profile_ids',[]):
        p=profiles[pid]
        notes.append(f'**{name}:** [Profil porównawczy: {p["name_source"]}](Wartosci_odzywcze_2026.md#{pid.lower()}) — nie przypisywać tych wartości do produktu bez potwierdzenia.')
    if item.get('variant_options_en'): notes.append(f'**{name} — warianty DLA:** '+', '.join(item['variant_options_en'])+'.')
    if item.get('conditional'): notes.append(f'**{name}:** element warunkowy; szczegóły w README i JSON.')
    return result

for case,nums in [('A','01-12'),('B','13-24')]:
    lines=[f'# MRE XLVI (2026) — Case {case}, menu {nums}', '', 'Wartości na porcję COMRAD, nie na 100 g. — = brak danych lub nie dotyczy; zero jest przepisaną wartością źródłową. Warianty są alternatywami. Pełny profil zawiera witaminy, minerały i uwagi jakościowe. [Opis i ograniczenia](README.md).', '']
    for m in d['menus']:
        if m['case']!=case: continue
        lines += [f'## Menu {m["menu_number"]:02d} — {m["name_en"]}', '',m['name_pl'],'']
        notes=[]
        lines+=header
        for item in m['components']: lines+=item_rows(item,notes)
        for item in m['components']:
            packet=item.get('accessory_packet_id')
            if packet:
                lines+=['',f'### Skład Accessory Packet {packet}', '', 'Rozwinięcie pakietu z tabeli powyżej; nie dodatkowy pakiet. Braki wartości gumy i soli nie oznaczają zera.', '']+header
                for child in d['accessory_packets'][packet]['components']: lines+=item_rows(child,notes)
        lines+=['','### Uwagi do menu','']
        lines+=['- '+s for s in list(dict.fromkeys(notes+m.get('notes_pl',[])))]
        lines+=['',f'[Źródło zawartości DLA]({m["source_url"]}); [źródło wartości COMRAD]({d["nutrition_source"]["url"]}), strona {m["comrad_reported_total"]["source_page"]}.','']
    save(f'Case_{case}_menu_{nums}_2026.md',lines)

labels=['Masa porcji (g)','Energia (kcal)','Białko (g)','Węglowodany (g)','Błonnik (g)','Tłuszcz (g)','Tłuszcze trans (g)','Cholesterol (mg)','Witamina A (IU)','Tiamina B1 (mg)','Ryboflawina B2 (mg)','Niacyna B3 (mg)','Witamina B6 (mg)','Witamina B12 (µg)','Witamina C (mg)','Witamina D (µg)','Witamina E (mg)','Foliany (µg)','Witamina K (µg)','Wapń (mg)','Fluor (mg)','Jod (µg)','Żelazo (mg)','Magnez (mg)','Fosfor (mg)','Potas (mg)','Selen (jednostka źródłowa NIEPOTWIERDZONA)','Sód (mg)','Cynk (mg)','Kwasy tłuszczowe jednonienasycone (g)','Kwasy tłuszczowe wielonienasycone (g)','Kwasy tłuszczowe nasycone (g)','Kwas linolowy (jednostka niepodana)','Kwas alfa-linolenowy (jednostka niepodana)','Cukry (g)','Kofeina (mg)']
lines=['# Pełne profile odżywcze MRE 2026','', '114 profili źródłowych. Wartości dotyczą porcji wskazanej przy profilu, nie 100 g. — oznacza pustą komórkę źródła. Zachowano dokładność liczb podaną przez COMRAD; nie jest to gwarancja dokładności pomiarowej. Nazwy i wartości pochodzą z tabeli źródłowej. Profile porównawcze nie stanowią potwierdzonego dopasowania do zawartości DLA.','', '**Jednostki:** nagłówek selenu w PDF brzmi „Sel (mg)”, ale jednostka wymaga potwierdzenia. Nie interpretować zapisanych liczb jako mg ani µg. Dla kwasu linolowego i alfa-linolenowego PDF nie podaje jednostek.','']
for pid,p in profiles.items():
    lines += [f'<a id="{pid.lower()}"></a>',f'## {p["name_source"]} — {pid}', '',f'Źródło: [COMRAD PDF](sources/HPRC_COMRAD_MRE_46_2026.pdf), strona {p["source_page"]}; menu: '+', '.join(map(str,sorted(set(p['source_menu_numbers']))))+'.','']
    lines += ['**Uwaga jakościowa:** '+n+'\n' for n in p['quality_notes_pl']]
    assert len(p['values'])==len(labels)
    lines += ['| Wartość | Na porcję |','|---|---:|']+[f'| {label} | {fmt(v)} |' for label,v in zip(labels,p['values'].values())]+['']
save('Wartosci_odzywcze_2026.md',lines)

assert [m['menu_number'] for m in d['menus']]==list(range(1,25))
assert Counter(m['case'] for m in d['menus'])=={'A':12,'B':12}
for m in d['menus']:
    for i in m['components']:
        for pid in i['nutrition'].get('profile_ids',[])+i['nutrition'].get('reference_profile_ids',[]): assert pid in profiles
raw=json.loads((ROOT/'sources/comrad_2026_raw.json').read_text(encoding='utf-8'))
for num in range(1,25):
    rs=[r for r in raw if r['menu_number']==num]
    total=next(r for r in rs if r['record_type']=='menu_total')['values_per_source_portion']
    for k in ['weight_g','energy_kcal','protein_g','carbohydrate_g','fat_g']:
        vals=[r['values_per_source_portion'][k] for r in rs if r['record_type']=='component']
        assert abs(sum(v or 0 for v in vals)-total[k])<.1,(num,k)
save('sources/VALIDATION.md',['# Kontrola danych','', '- 24 menu, po 12 w Case A i Case B; numeracja 1–24 bez luk.', '- Wszystkie odwołania produktów do profili odżywczych istnieją.', '- 114 profili; 36 pól na profil. Puste komórki zachowane jako null.', '- Masa, kcal, białko, węglowodany i tłuszcz z wierszy COMRAD odtwarzają opublikowane sumy wszystkich 24 menu z tolerancją 0,1 jednostki (zaokrąglenia). Puste komórki pominięto wyłącznie w tej kontroli sum; w danych nadal oznaczają brak danych.', '- Sprawdzono wizualnie wszystkie 4 strony pobranego PDF COMRAD. Liczby odczytano według położenia kolumn.', '- Kontrola nie potwierdza poprawności merytorycznej samego źródła. Rozbieżności kcal/makro i kofeiny oznaczono przy profilach.', '- Oryginalnego PDF DLA nie udało się pobrać (HTTP 403); zawartość przepisano z indeksowanego tekstu. To ogranicza weryfikację listy zawartości.'])
print('Wygenerowano tabele 24 menu i 114 profili. Kontrole zaliczone.')
