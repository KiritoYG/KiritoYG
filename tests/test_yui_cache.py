"""Regression tests for new messages retaining stale browser/CDN images."""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yui_brain import version_card_urls


def document(day="2026-09-25", note="Keep small changes easy to review."):
    return (f'<!-- YUI_START -->\n{day} · {note}\n<!-- YUI_END -->\n'
            '<source media="(max-width: 600px)" srcset="./assets/yui-dialogue-mobile.svg">\n'
            '<img src="./assets/yui-dialogue.svg" alt="Yui">\n'
            '<img src="./assets/player-info.svg">\n').encode("utf-8")


class YuiCacheTests(unittest.TestCase):
    def test_both_card_urls_are_versioned_and_other_assets_are_unchanged(self):
        result = version_card_urls(document())
        tokens = re.findall(rb"\?v=([a-f0-9]{16})", result)
        self.assertEqual(len(tokens), 2)
        self.assertEqual(tokens[0], tokens[1])
        self.assertEqual(result.count(b"https://raw.githubusercontent.com/KiritoYG/KiritoYG/main/assets/"), 2)
        self.assertIn(b'<img src="./assets/player-info.svg">', result)
        self.assertIn(b'2026-09-25', result)

    def test_same_content_is_stable_but_a_new_date_or_message_changes_urls(self):
        def token(content):
            return re.search(rb"\?v=([a-f0-9]{16})", version_card_urls(content))[1]
        original = document()
        self.assertEqual(version_card_urls(version_card_urls(original)), version_card_urls(original))
        self.assertNotEqual(token(original), token(document(day="2026-09-26")))
        self.assertNotEqual(token(original), token(document(note="Logs make debugging easier.")))


if __name__ == "__main__":
    unittest.main()
