"""Offline checks for safe daily-note/card updates (standard library only)."""

import contextlib
import io
import re
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import yui_brain
import yui_card

SVG = "{http://www.w3.org/2000/svg}"
NOTE = "一歩ずつ、自分のペースで進めましょう。"
DOCUMENT = (
    "# Keep this introduction\r\n\r\n"
    "<details><summary>今日のメッセージ · 文字版</summary>\r\n\r\n"
    "<!-- YUI_START -->\r\n1980-01-02 · " + NOTE + "\r\n"
    "<!-- YUI_END -->\r\n\r\n</details>\r\n\r\n"
    "## Keep these projects\r\n- Existing project link\r\n"
).encode("utf-8")


def png_bytes(color):
    def chunk(name, payload):
        return (struct.pack(">I", len(payload)) + name + payload
                + struct.pack(">I", zlib.crc32(name + payload) & 0xffffffff))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\0" + bytes(color)))
            + chunk(b"IEND", b""))


class YuiCardTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.readme = self.root / "README.md"
        self.readme.write_bytes(DOCUMENT)
        self.assets = self.root / "assets"
        self.assets.mkdir()
        (self.assets / "yui-avatar-open.png").write_bytes(png_bytes((220, 235, 245)))
        (self.assets / "yui-avatar-closed.png").write_bytes(png_bytes((80, 100, 120)))
        self.cards = [self.assets / "yui-dialogue.svg",
                      self.assets / "yui-dialogue-mobile.svg"]
        for index, card in enumerate(self.cards):
            card.write_bytes(f"old card {index}".encode())

    def snapshot(self):
        return {path: path.read_bytes() for path in [self.readme, *self.cards]}

    def test_50_cjk_characters_wrap_and_fit_both_cards(self):
        text = "あ" * 50
        yui_brain.update_profile(text, "2026-09-25", self.readme)
        for card, expected_lines, max_units in zip(self.cards, (3, 4), (23, 16)):
            svg = ET.fromstring(card.read_bytes())
            message = svg.find(f"{SVG}text[@id='message']")
            lines = message.findall(f"{SVG}tspan")
            self.assertEqual(len(lines), expected_lines)
            self.assertEqual("".join(line.text for line in lines), text)
            for line in lines:
                self.assertLessEqual(sum(yui_card._char_units(char) for char in line.text),
                                     max_units)
                self.assertLess(float(line.attrib["y"]), float(svg.attrib["height"]) - 20)
            images = svg.findall(f".//{SVG}image")
            self.assertEqual(len(images), 2)
            self.assertTrue(all(image.attrib["href"].startswith("data:image/png;base64,")
                                for image in images))
            self.assertIsNone(svg.find(f".//{SVG}script"))
            self.assertIsNone(svg.find(f".//{SVG}foreignObject"))

    def test_xml_escaping_retains_ampersands_quotes_and_japanese(self):
        text = 'LLM & Agentの実験は"一歩ずつ"。'
        yui_brain.update_profile(text, "2026-09-25", self.readme)
        for card in self.cards:
            encoded = card.read_bytes()
            self.assertIn(b"&amp;", encoded)
            self.assertIn(b"&quot;", encoded)
            svg = ET.fromstring(encoded)
            message = svg.find(f"{SVG}text[@id='message']")
            self.assertEqual("".join(line.text for line in message), text)

    def test_japanese_line_breaks_keep_punctuation_with_text(self):
        for text in ("あ" * 23 + "。続きです。", "あ" * 22 + "「続きです」"):
            lines = yui_card.wrap_text(text, 23)
            self.assertEqual("".join(lines), text)
            self.assertFalse(any(line.startswith("。") for line in lines))
            self.assertFalse(any(line.endswith("「") for line in lines))
            self.assertTrue(all(sum(yui_card._char_units(char) for char in line) <= 23
                                for line in lines))

    def test_render_is_byte_deterministic_and_preserves_marker_date(self):
        self.assertTrue(yui_card.write_yui_cards(self.readme))
        first = self.snapshot()
        self.assertFalse(yui_card.write_yui_cards(self.readme))
        self.assertEqual(self.snapshot(), first)
        self.assertEqual(first[self.readme], DOCUMENT)
        for card in self.cards:
            svg = ET.fromstring(first[card])
            self.assertEqual(svg.find(f"{SVG}text[@id='date']").text,
                             "1980-01-02 · JST")
            self.assertIn("prefers-reduced-motion", first[card].decode())

    def test_missing_or_duplicate_markers_preserve_all_assets(self):
        for broken in (DOCUMENT.replace(b"<!-- YUI_START -->", b"missing"),
                       DOCUMENT + b"<!-- YUI_START -->\r\n"):
            with self.subTest(broken=broken[:30]):
                self.readme.write_bytes(broken)
                before = self.snapshot()
                with self.assertRaises(yui_card.CardError):
                    yui_card.write_yui_cards(self.readme)
                self.assertEqual(self.snapshot(), before)
                with self.assertRaises(yui_brain.UpdateError):
                    yui_brain.update_profile(NOTE, "2026-09-25", self.readme)
                self.assertEqual(self.snapshot(), before)

    def test_missing_or_invalid_avatar_preserves_readme_and_cards(self):
        avatar = self.assets / "yui-avatar-closed.png"
        avatar.unlink()
        before = self.snapshot()
        with self.assertRaises(OSError):
            yui_brain.update_profile(NOTE, "2026-09-25", self.readme)
        self.assertEqual(self.snapshot(), before)
        avatar.write_bytes(b"invalid png")
        with self.assertRaises(yui_card.CardError):
            yui_brain.update_profile(NOTE, "2026-09-25", self.readme)
        self.assertEqual(self.snapshot(), before)

    def test_second_card_render_failure_preserves_all_published_files(self):
        before = self.snapshot()
        original_render = yui_card.render_card
        def fail_mobile(*args, **kwargs):
            if kwargs.get("mobile"):
                raise yui_card.CardError("Rendering failed.")
            return original_render(*args, **kwargs)
        with patch.object(yui_card, "render_card", side_effect=fail_mobile):
            with self.assertRaises(yui_card.CardError):
                yui_brain.update_profile(NOTE, "2026-09-25", self.readme)
        self.assertEqual(self.snapshot(), before)

    def test_replace_failure_rolls_back_earlier_replacement(self):
        before = self.snapshot()
        original_replace = yui_card.os.replace
        calls = 0
        def fail_once(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated write failure")
            return original_replace(source, destination)
        with patch.object(yui_card.os, "replace", side_effect=fail_once):
            with self.assertRaises(OSError):
                yui_card.write_yui_cards(self.readme)
        self.assertEqual(self.snapshot(), before)

    def test_api_failure_in_main_never_calls_the_updater(self):
        before = self.snapshot()
        with patch.object(yui_brain, "get_yui_insight",
                          side_effect=yui_brain.UpdateError("Yui generation failed.")), \
             patch.object(yui_brain, "update_profile") as update, \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(yui_brain.main(), 1)
            update.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_successful_update_changes_note_and_both_cards_only(self):
        insight = "パパ、今日も小さな工夫を一つ試してみましょう！"
        self.assertTrue(yui_brain.update_profile(insight, "2026-09-25", self.readme))
        updated = self.readme.read_bytes()
        marker = re.compile(rb"(?m)^<!-- YUI_START -->\r?$[\s\S]*?^<!-- YUI_END -->\r?$")
        self.assertEqual(marker.sub(b"NOTE", updated), marker.sub(b"NOTE", DOCUMENT))
        self.assertEqual(updated.count(b"<!-- YUI_START -->"), 1)
        self.assertEqual(updated.count(b"<!-- YUI_END -->"), 1)
        self.assertIsNone(re.search(rb"(?<!\r)\n", updated))
        for card in self.cards:
            svg = ET.fromstring(card.read_bytes())
            message = svg.find(f"{SVG}text[@id='message']")
            self.assertEqual("".join(line.text for line in message), insight)
            self.assertEqual(svg.find(f"{SVG}text[@id='date']").text,
                             "2026-09-25 · JST")
        self.assertFalse(yui_brain.update_profile(insight, "2026-09-25", self.readme))


if __name__ == "__main__":
    unittest.main()
