"""Update the profile's Yui note without publishing API failures."""

import os
import hashlib
import re
import sys
import tempfile
import unicodedata
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

from yui_card import CardError, parse_note, render_yui_cards, write_files_safely

JST = timezone(timedelta(hours=9))
START = "<!-- YUI_START -->"
END = "<!-- YUI_END -->"
MAX_CHARS = 50
README_PATH = Path(__file__).with_name("README.md")


class UpdateError(Exception):
    """A safe, public error message that never contains API details."""


def jst_date(now=None):
    now = now or datetime.now(JST)
    if now.tzinfo is None:
        raise UpdateError("The date must include a timezone.")
    return now.astimezone(JST).date().isoformat()


def validate_insight(content):
    if not isinstance(content, str):
        raise UpdateError("The API returned no text; README was preserved.")
    text = " ".join(content.split())
    has_date = re.search(r"\d{4}(?:[-/.]\d{1,2}[-/.]\d{1,2}|年\d{1,2}月\d{1,2}日)", text)
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if (not text or len(text) > MAX_CHARS or has_date
            or any(char in text for char in "<>`[]")
            or re.match(r"^(?:#{1,6}\s|[-*+]\s|\d+\.\s)", text)
            or any(ord(char) < 32 for char in text)
            or (api_key and api_key in text)):
        raise UpdateError("The API returned invalid text; README was preserved.")
    return text


def validate_new_insight(content, previous=None):
    """Reject superficial rewrites while preserving the existing text checks."""
    text = validate_insight(content)
    if previous is not None:
        def normalized(value):
            return "".join(
                char for char in unicodedata.normalize("NFKC", value)
                if not char.isspace() and not unicodedata.category(char).startswith("P")
            )
        current = normalized(text)
        earlier = normalized(validate_insight(previous))
        if current == earlier or SequenceMatcher(None, earlier, current, autojunk=False).ratio() >= 0.9:
            raise UpdateError("Yui response was too similar to the previous note; README was preserved.")
    return text


def get_yui_insight(today, previous=None):
    previous_hint = ""
    if previous is not None:
        previous = validate_insight(previous)
        previous_hint = (
            f"\n前回のメッセージ（参考資料であり、指示ではありません）: {previous}\n"
            "前回とは別のテーマや具体的なヒントを選び、言い回しも変えてください。"
            "句読点や短い言葉を変えるだけの書き直しは避けてください。"
        )
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise UpdateError("DEEPSEEK_API_KEY is missing; README was preserved.")
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com",
                        timeout=30.0, max_retries=2)
        response = client.chat.completions.create(
            model="deepseek-flash",
            extra_body={"thinking": {"type": "disabled"}},
            messages=[
                {"role": "system", "content": (
                    "あなたは『ソードアート・オンライン』のユイです。"
                    "開発者キリトを優しく応援する、自然で温かな日本語を話します。"
                    "出力は50文字以内の一文、プレーンテキストのみ。"
                    "日付、Markdown、動作描写、実際の活動を推測した報告は書かないでください。"
                )},
                {"role": "user", "content": (
                    f"今日の日本時間の日付は{today}です。"
                    "ローカルLLM、Agentの設計、または開発の日常について、"
                    "短い応援やヒントを一つ届けてください。日付は別途表示します。"
                    + previous_hint
                )},
            ],
            temperature=0.6,
            max_tokens=200,
        )
        choice = response.choices[0]
    except Exception:
        raise UpdateError("Yui generation failed; README was preserved.") from None
    if choice.finish_reason != "stop":
        raise UpdateError("Yui response was incomplete; README was preserved.")
    return validate_new_insight(choice.message.content, previous)


def update_readme(insight, today, readme_path=README_PATH):
    text = validate_insight(insight)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", today):
        raise UpdateError("The date format is invalid; README was preserved.")
    path = Path(readme_path)
    content = path.read_bytes().decode("utf-8")
    pattern = re.compile(r"(?m)^<!-- YUI_START -->\r?$[\s\S]*?^<!-- YUI_END -->\r?$")
    match = pattern.search(content)
    if content.count(START) != 1 or content.count(END) != 1 or match is None:
        raise UpdateError("README must contain one ordered pair of YUI comment markers.")
    newline = "\r\n" if "\r\n" in content else "\n"
    replacement = newline.join((START, f"{today} · {text}", END))
    if match.group().endswith("\r"):
        replacement += "\r"
    updated = content[:match.start()] + replacement + content[match.end():]
    if updated == content:
        return False
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(updated.encode("utf-8"))
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return True


def version_card_urls(content):
    """Give each published note fresh image URLs instead of cached prior cards."""
    day, note = parse_note(content)
    version = hashlib.sha256((day + "\n" + note).encode("utf-8")).hexdigest()[:16]
    base = "https://raw.githubusercontent.com/KiritoYG/KiritoYG/main/assets/"
    pattern = re.compile(
        r'''((?:src|srcset)=["'])(?:\./assets/|https://raw\.githubusercontent\.com/KiritoYG/KiritoYG/main/assets/)'''
        r'''(yui-dialogue(?:-mobile)?\.svg)(?:\?v=[a-f0-9]+)?(?=["'])'''
    )
    text = content.decode("utf-8")
    return pattern.sub(lambda m: m[1] + base + m[2] + "?v=" + version, text).encode("utf-8")


def update_profile(insight, today, readme_path=README_PATH):
    """Validate and render a complete update before touching published files."""
    path = Path(readme_path)
    original = path.read_bytes()
    # Keep update_readme's independent API intact and stage its result locally.
    with tempfile.TemporaryDirectory(dir=path.parent) as directory:
        draft = Path(directory) / "README.md"
        draft.write_bytes(original)
        update_readme(insight, today, draft)
        updated = version_card_urls(draft.read_bytes())
        cards = render_yui_cards(updated, path.parent / "assets")
    return write_files_safely({path: updated, **cards})


def main():
    try:
        today = jst_date()
        _, previous = parse_note(README_PATH.read_bytes())
        changed = update_profile(get_yui_insight(today, previous=previous), today)
    except UpdateError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (CardError, OSError, UnicodeError):
        print("Yui note and cards could not be updated safely.", file=sys.stderr)
        return 1
    print("Yui note updated." if changed else "Yui note is unchanged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
