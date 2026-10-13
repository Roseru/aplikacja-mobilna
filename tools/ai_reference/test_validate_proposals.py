"""Mutation checks for the read-only proposal validator, no network or file changes."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import validate_proposals as validator


class ProposalChecks(unittest.TestCase):
    def setUp(self):
        self.packet = validator.PACKET
        self.original_text = Path.read_text
        self.original_bytes = Path.read_bytes
        self.doc = json.loads((self.packet / "reference_proposals.json").read_text(encoding="utf-8"))
        self.index = json.loads((self.packet / "candidate_index.json").read_text(encoding="utf-8"))

    def check_mutation(self, mutate, change_index=False):
        doc, index = copy.deepcopy(self.doc), copy.deepcopy(self.index)
        mutate(doc, index)

        def read_text(path, *args, **kwargs):
            if path == self.packet / "reference_proposals.json":
                return json.dumps(doc)
            if change_index and path == self.packet / "candidate_index.json":
                return json.dumps(index)
            return self.original_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", read_text), self.assertRaises(AssertionError):
            validator.validate()

    def test_pending_is_never_runnable(self):
        summary, _ = validator.validate()
        self.assertFalse(summary["runnable"])
        self.assertEqual(summary["human_qualified"], 0)
        self.check_mutation(lambda d, i: d.update(runnable=True, provider_consents=30))

    def test_changed_hash(self):
        self.check_mutation(lambda d, i: d["cases"][0].update(image_sha256="0" * 64))

    def test_changed_bytes(self):
        target = self.packet / self.doc["cases"][0]["image"]

        def read_bytes(path):
            raw = self.original_bytes(path)
            return raw[:-1] + bytes([raw[-1] ^ 1]) if path == target else raw

        with patch.object(Path, "read_bytes", read_bytes), self.assertRaises(AssertionError):
            validator.validate()

    def test_normalized_alias_collision(self):
        self.check_mutation(
            lambda d, i: d["cases"][8]["proposal"]["main_components"][1]
            ["accepted_aliases"].append(" CHERRY   TOMATOES ")
        )

    def test_missing_reference_locator(self):
        self.check_mutation(
            lambda d, i: d["cases"][0]["reference_source"].update(locator="dish_nonexistent")
        )

    def test_changed_reference_record_hash(self):
        self.check_mutation(
            lambda d, i: d["cases"][0]["reference_source"].update(record_sha256="0" * 64)
        )

    def test_duplicate_image_with_consistent_index(self):
        def mutate(doc, index):
            for key in ("image", "image_sha256"):
                doc["cases"][1][key] = doc["cases"][0][key]
                index["candidates"][1][key] = index["candidates"][0][key]
            index["candidates"][1]["bytes"] = index["candidates"][0]["bytes"]

        self.check_mutation(mutate, change_index=True)


if __name__ == "__main__":
    unittest.main()
