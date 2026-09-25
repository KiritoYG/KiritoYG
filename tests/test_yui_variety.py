"""Offline checks that Yui publishes a new thought rather than a cosmetic edit."""

import contextlib
import io
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import yui_brain

PREVIOUS = "パパ、今日も一歩ずつ進めば大丈夫だよ！"
FRESH = "Agentの役割を小さく分けると、試したいことが見えてきますよ。"


def fake_openai(text):
    module = types.ModuleType("openai")
    client = Mock()
    client.chat.completions.create.return_value = types.SimpleNamespace(choices=[
        types.SimpleNamespace(finish_reason="stop", message=types.SimpleNamespace(content=text))
    ])
    module.OpenAI = Mock(return_value=client)
    return module, client


class YuiVarietyTests(unittest.TestCase):
    def test_punctuation_whitespace_and_width_changes_are_rejected(self):
        cases = (
            (PREVIOUS, "パパ、今日も一歩ずつ進めば大丈夫だよ。"),
            ("ＡＩの実験、焦らず進めよう！", "AIの実験 焦らず進めよう。"),
        )
        for previous, candidate in cases:
            with self.subTest(candidate=candidate):
                with self.assertRaisesRegex(yui_brain.UpdateError, "too similar"):
                    yui_brain.validate_new_insight(candidate, previous)

    def test_adding_kitto_to_the_previous_sentence_is_rejected(self):
        with self.assertRaisesRegex(yui_brain.UpdateError, "too similar"):
            yui_brain.validate_new_insight(
                "パパ、今日も一歩ずつ進めばきっと大丈夫だよ。", PREVIOUS)

    def test_distinct_topic_is_accepted_and_existing_limits_still_apply(self):
        self.assertEqual(yui_brain.validate_new_insight(FRESH, PREVIOUS), FRESH)
        with self.assertRaises(yui_brain.UpdateError):
            yui_brain.validate_new_insight("あ" * 51, PREVIOUS)

    def test_previous_is_in_prompt_and_api_parameters_stay_unchanged(self):
        module, client = fake_openai(FRESH)
        with patch.dict(sys.modules, {"openai": module}), \
                patch.dict(os.environ, {"DEEPSEEK_API_KEY": "offline-test-key"}):
            self.assertEqual(yui_brain.get_yui_insight("2026-09-25", PREVIOUS), FRESH)
        module.OpenAI.assert_called_once_with(
            api_key="offline-test-key", base_url="https://api.deepseek.com",
            timeout=30.0, max_retries=2)
        client.chat.completions.create.assert_called_once()
        options = client.chat.completions.create.call_args.kwargs
        self.assertEqual(set(options), {"model", "extra_body", "messages", "temperature", "max_tokens"})
        self.assertEqual(options["model"], "deepseek-flash")
        self.assertEqual(options["extra_body"], {"thinking": {"type": "disabled"}})
        self.assertEqual(options["temperature"], 0.6)
        self.assertEqual(options["max_tokens"], 200)
        self.assertIn(PREVIOUS, options["messages"][1]["content"])
        self.assertIn("別のテーマ", options["messages"][1]["content"])
        self.assertIn("50文字以内", options["messages"][0]["content"])

    def test_main_reads_current_note_and_passes_it_to_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            readme = Path(directory) / "README.md"
            readme.write_text("<!-- YUI_START -->\n2026-09-24 · " + PREVIOUS
                              + "\n<!-- YUI_END -->\n", encoding="utf-8")
            with patch.object(yui_brain, "README_PATH", readme), \
                    patch.object(yui_brain, "jst_date", return_value="2026-09-25"), \
                    patch.object(yui_brain, "get_yui_insight", return_value=FRESH) as generate, \
                    patch.object(yui_brain, "update_profile", return_value=True) as update, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(yui_brain.main(), 0)
            generate.assert_called_once_with("2026-09-25", previous=PREVIOUS)
            update.assert_called_once_with(FRESH, "2026-09-25")

    def test_repeated_response_uses_one_request_and_preserves_published_files(self):
        module, client = fake_openai(PREVIOUS.replace("！", "。"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            readme = root / "README.md"
            readme.write_text("# Existing profile\n<!-- YUI_START -->\n2026-09-24 · "
                              + PREVIOUS + "\n<!-- YUI_END -->\n", encoding="utf-8")
            assets = root / "assets"
            assets.mkdir()
            cards = [assets / "yui-dialogue.svg", assets / "yui-dialogue-mobile.svg"]
            for card in cards:
                card.write_bytes(b"existing card")
            before = {path: path.read_bytes() for path in [readme, *cards]}
            error = io.StringIO()
            with patch.dict(sys.modules, {"openai": module}), \
                    patch.dict(os.environ, {"DEEPSEEK_API_KEY": "offline-test-key"}), \
                    patch.object(yui_brain, "README_PATH", readme), \
                    patch.object(yui_brain, "jst_date", return_value="2026-09-25"), \
                    patch.object(yui_brain, "update_profile") as update, \
                    contextlib.redirect_stderr(error):
                self.assertEqual(yui_brain.main(), 1)
                update.assert_not_called()
            client.chat.completions.create.assert_called_once()
            self.assertIn("too similar", error.getvalue())
            self.assertNotIn("offline-test-key", error.getvalue())
            self.assertEqual({path: path.read_bytes() for path in before}, before)


if __name__ == "__main__":
    unittest.main()
