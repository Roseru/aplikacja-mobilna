# Commons: 14 kandydatów do oceny - osoba 2

## Aktualny wynik offline 13.10.2026

Pierwotne14 obrazy pozostają zachowane. Dodano2 oryginały z batch źródeł
(commons-19/20); trzeci downloadHTTP429 przerwał próbę. commons-19 peanut butter
proponowany zamiast commons-08; commons-20 zamknięty zestaw odrzucony.
Łącznie Commons:12 PROPOSED (8rations/4unreadable),4REJECTED.
[Propozycje](../reference_proposals.json) i [galeria](../GALLERY.md) są aktualne;
niższy opis10/4 dotyczy pierwotnego pozyskania. Human/consents/uploads=0.

Status: **CANDIDATES_REVIEW_REQUIRED**, not a runnable manifest and not E7-R PASS.

`index.json` selects 14 different photographs: 10 rations/components and 4 food photos whose contents are naturally obscured by opaque leaf wrapping. All selected images were downloaded and inspected with `view_image`. No image was generated, cropped, blurred or edited locally. Server thumbnails are explicitly linked to original uploads in metadata. The historical Commons source of commons-01 itself declares prior author cropping; this is disclosed, not concealed.

18 distinct source photographs were actually downloaded (20 successful image downloads, including 2 smaller replacements to keep dimensions within 1600 px). Four technically weak photos were rejected from the unreadable group because visible food remained recognisable. `audit-index.json` keeps all 18 and the rejection reasons; only 14 selected entries go into the review packet. Every selected stored photo has a unique SHA-256, maximum dimension 1600 px and size under 5 MiB; read-only codec/dimension/hash checks passed.

Each selected entry records source page, author, attribution/credit, CC BY / CC BY-SA / public-domain rights, license URL, original URL, requested and actual downloaded variant, download Last-Modified, Commons upload timestamp/SHA-1, exact downloaded SHA-256 and evidence JSON. `ATTRIBUTION.md` is the reusable credit list. Rights metadata is from the primary Commons imageinfo API and description pages; public-domain entries may have no Creative Commons license URL, as their official-government status is recorded in source evidence. Source descriptions are retained as HTML to preserve provenance, not as instructions.

`proposed_main_components` and readability are AI-assisted **drafts for an independent human**, not frozen human reference. The ten ration candidates include historic emergency/commercial packaging and Army experimental display photographs, not ten verified current US 2026 menu variants. commons-08 is a meal-kit case label; replace it if the reviewer requires opened food. commons-03/04 lack visible labels and rely on linked source descriptions for whole-item identity; commons-07 has additional visible sides not independently confirmed. commons-10 shows separate fruit examples, which must not be summed as one ration. No mass, calories, current catalogue match, producer confirmation or official-product status is invented.

The four selected unreadable candidates (commons-15–18) show tied/folded leaf packages with food hidden inside and no readable identity label. Source descriptions establish real food rather than empty containers. Exact identification from the picture alone is unsupported; drafts therefore have readable=false and empty components. Their similar concealment mechanism is a coverage limitation, despite distinct photographs/subjects/authors. Human classification remains required.

Qualified human references: **0**. Provider-specific consent: **0**. Google/Gemini uploads or calls: **0**. Licenses permit reuse subject to their terms but do not substitute for the application's explicit reference-test/provider notice and consent. O3 runtime/Free Tier and the independent human reference must be completed before any actual run. This folder alone does not meet the 30-photo full corpus requirement.

Source API hit a 429 after individual lookups; no immediate replay was made. Subsequent bounded lookups were batched. Fetch scripts are evidence of preparation, not CI or live test commands; do not rerun unnecessarily. Files stay in the authorized draft directory; no repository commit/push, new chat, billing, credential lookup or provider upload was performed.

Pakiet repozytorium zawiera tylko 14 wybranych fotografii; audit-index zachowuje metadane18 źródeł, a 4 odrzucone obrazy pozostają prywatnym dowodem. Skrypty robocze nie są publikowane. [Galeria](../GALLERY.md) i [proces przyjęcia](../README.md).
