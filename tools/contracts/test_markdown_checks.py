"""Regression coverage for archived examples and active documentation links."""
import tempfile
import unittest
from pathlib import Path

from markdown_checks import check_local_links


class MarkdownLinksTest(unittest.TestCase):
    def check(self, contents):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'doc.md'
            path.write_text(contents, encoding='utf-8')
            (path.parent / 'other file.md').touch()
            return check_local_links(path)

    def test_broken_active_link_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, 'Broken local link'):
            self.check('[missing](TABLICA.md)')

    def test_archived_backtick_and_tilde_fences_are_ignored(self):
        for fence in ('```markdown', '~~~markdown', '   ```markdown'):
            with self.subTest(fence=fence):
                self.assertEqual(self.check(f'{fence}\n[old](TABLICA.md)\n{fence.strip()[:3]}\n'), 0)

    def test_shorter_or_different_fence_does_not_end_archive(self):
        for inner in ('```', '~~~', '```` trailing text'):
            with self.subTest(inner=inner):
                self.assertEqual(self.check(f'````markdown\n{inner}\n[old](TABLICA.md)\n````\n'), 0)

    def test_link_after_closing_fence_is_checked(self):
        with self.assertRaisesRegex(AssertionError, 'Broken local link'):
            self.check('```markdown\n[old](TABLICA.md)\n````\n[active](missing.md)')

    def test_percent_encoded_local_link_is_counted(self):
        self.assertEqual(self.check('[valid](other%20file.md#section)\n[web](https://example.com)\n[section](#section)'), 1)

    def test_invalid_backtick_info_does_not_hide_active_link(self):
        with self.assertRaisesRegex(AssertionError, 'Broken local link'):
            self.check('```bad`info\n[active](missing.md)')


if __name__ == '__main__':
    unittest.main()
