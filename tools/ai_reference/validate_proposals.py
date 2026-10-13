"""Read-only offline checks of the E7 photo proposal packet; never uploads."""
import hashlib
import json
import sys
import unicodedata
from collections import Counter
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
PACKET = ROOT / "Random Data/AI_REFERENCE_E7_R_2026-10-13"


def normalize(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def validate(packet=PACKET):
    doc = json.loads((packet / "reference_proposals.json").read_text(encoding="utf-8"))
    index = json.loads((packet / "candidate_index.json").read_text(encoding="utf-8"))
    assert doc["document_type"] == "e7-reference-proposals-NOT-RUNNABLE"
    assert doc["runnable"] is False
    assert doc["human_qualified"] == doc["provider_consents"] == doc["provider_uploads"] == 0
    assert doc["expected_profile"] is doc["notice_version"] is doc["o3_confirmation"] is None
    replacement = json.loads((packet / "commons/replacement-index.json").read_text(encoding="utf-8"))
    candidates = index["candidates"] + replacement
    assert len(doc["cases"]) == len(candidates)
    annotations = {
        a["source_id"]: a
        for a in json.loads((packet / "nutrition5k/annotations.json").read_text(encoding="utf-8"))
    }
    commons = {
        a["case_id"]: a
        for a in json.loads((packet / "commons/index.json").read_text(encoding="utf-8"))
    }
    replacement_proof = json.loads(
        (packet / "commons/replacement-source-evidence.json").read_text(encoding="utf-8")
    )["query"]["pages"]
    source = {c["candidate_id"]: c for c in candidates}
    assert len(source) == len(candidates)
    ids, hashes, pixels = set(), set(), set()
    decisions, groups = Counter(), Counter()
    gallery = (packet / "GALLERY.md").read_text(encoding="utf-8")
    audit = []
    for c in doc["cases"]:
        cid = c["case_id"]
        assert cid not in ids
        ids.add(cid)
        original = source[cid]
        assert c["image"] == original["image"]
        assert c["image_sha256"] == original["image_sha256"]
        relative = Path(c["image"])
        assert not relative.is_absolute() and ".." not in relative.parts and ":" not in c["image"]
        path = packet / relative
        assert not path.is_symlink()
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        assert digest == c["image_sha256"] and digest not in hashes, cid
        hashes.add(digest)
        assert len(raw) == original["bytes"] <= 5 * 1024 * 1024
        with Image.open(path) as im:
            im.load()
            assert im.format in ("JPEG", "PNG", "WEBP")
            assert max(im.size) <= 4096 and im.width * im.height <= 16000000
            pixel_hash = hashlib.sha256(str(im.size).encode() + im.convert("RGB").tobytes()).hexdigest()
            assert pixel_hash not in pixels, cid
            pixels.add(pixel_hash)
            exif = im.getexif()
            gps = exif.get_ifd(34853) if 34853 in exif else {}
            assert not gps, cid
            audit.append({"case_id": cid, "sha256": digest, "bytes": len(raw),
                          "codec": im.format, "width": im.width, "height": im.height,
                          "exif_tags": sorted(exif.keys()), "gps_present": False,
                          "metadata_keys": sorted(im.info.keys()), "rgb_pixel_sha256": pixel_hash})
        assert c["photo_source"]["url"] == original["source_url"]
        assert c["photo_source"]["license"] == original["license"]
        assert (packet / c["photo_source"]["evidence"]).is_file()
        assert c["photo_source"]["attribution"]
        ref = c["reference_source"]
        if cid.startswith("n5-"):
            annotation = annotations[original["source_id"]]
            assert ref["locator"] == annotation["source_id"]
            record_hash = hashlib.sha256(annotation["raw_record"].encode("utf-8")).hexdigest()
            assert ref["record_sha256"] == annotation["source_record_utf8_no_eol_sha256"] == record_hash
        elif cid in commons:
            assert ref["locator"] == cid
            assert c["photo_source"]["attribution"] == commons[cid]["author"]
            assert c["photo_source"]["url"] == commons[cid]["source_page"]
            assert c["photo_source"]["license"] == commons[cid]["license"]
        else:
            page = next(x for x in replacement_proof.values()
                        if x["title"] == original["source_id"])
            info = page["imageinfo"][0]
            assert ref["locator"] == page["title"]
            assert hashlib.sha1(raw).hexdigest() == original["source_sha1"] == info["sha1"]
            assert c["photo_source"]["license"] == info["extmetadata"]["LicenseShortName"]["value"]
            assert c["photo_source"]["attribution"] == info["extmetadata"]["Artist"]["value"]
        assert c["human_reference"] is c["provider_consent"] is c["nonsensitive_approval"] is None
        assert c["approval_status"] == "HUMAN_REVIEW_PENDING"
        assert c["decision"] in ("PROPOSED", "REJECTED", "UNRESOLVED")
        p = c["proposal"]
        assert p["reviewer"] is p["reviewed_at"] is None
        assert p["origin"] == "LLM_PROPOSAL_NOT_HUMAN_APPROVAL"
        aliases, labels = set(), set()
        for comp in p["main_components"]:
            assert set(comp) == {"label", "accepted_aliases"}
            label = normalize(comp["label"])
            assert label and label not in labels
            labels.add(label)
            assert 1 <= len(comp["accepted_aliases"]) <= 20
            for alias in comp["accepted_aliases"]:
                alias = normalize(alias)
                assert alias and alias not in aliases, cid
                aliases.add(alias)
            assert label in aliases
        if c["decision"] == "PROPOSED":
            assert p["readable"] is (c["group"] != "unreadable")
            assert bool(p["main_components"]) is p["readable"]
            assert (packet / c["reference_source"]["evidence"]).is_file()
            groups[c["group"]] += 1
        assert f"### {cid} " in gallery
        assert f"![{cid}]({c['image']})" in gallery
        assert digest in gallery
        assert c["decision"] in gallery.split(f"### {cid} ", 1)[1].split("### ", 1)[0]
        decisions[c["decision"]] += 1
    assert ids == set(source)
    summary = {"examined": len(ids), "technically_valid": len(audit),
               "decisions": dict(decisions), "proposed_groups": dict(groups),
               "human_qualified": 0, "provider_consents": 0, "provider_uploads": 0,
               "runnable": False, "status": "OFFLINE_PACKET_VALID_NOT_RUNNABLE"}
    assert summary == doc["summary"]
    return summary, audit


if __name__ == "__main__":
    try:
        summary, _ = validate()
        print(json.dumps(summary, ensure_ascii=False))
    except (AssertionError, KeyError, ValueError, OSError) as exc:
        print("INVALID_OFFLINE_PACKET: " + str(exc), file=sys.stderr)
        raise SystemExit(2)

