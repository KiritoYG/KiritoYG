"""Render self-contained Yui dialogue cards from the README's existing note."""

import argparse
import base64
import html
import os
import re
import struct
import sys
import tempfile
import unicodedata
import zlib
from datetime import date
from pathlib import Path

START = "<!-- YUI_START -->"
END = "<!-- YUI_END -->"
DEFAULT_README = Path(__file__).with_name("README.md")
FONT = "'Noto Sans JP','Yu Gothic','Hiragino Kaku Gothic ProN',Meiryo,sans-serif"


class CardError(Exception):
    """A public error message that never contains source text or credentials."""


def parse_note(content):
    """Read exactly one dated, plain-text note without consulting the clock."""
    if isinstance(content, bytes):
        content = content.decode("utf-8")
    pattern = re.compile(
        r"(?m)^<!-- YUI_START -->\r?\n([^\r\n]+)\r?\n<!-- YUI_END -->\r?$"
    )
    match = pattern.search(content)
    if content.count(START) != 1 or content.count(END) != 1 or match is None:
        raise CardError("README must contain one dated Yui note between its markers.")
    note = re.fullmatch(r"(\d{4}-\d{2}-\d{2}) · (.+)", match.group(1))
    if note is None:
        raise CardError("The Yui note has an invalid date or text format.")
    day, text = note.groups()
    try:
        date.fromisoformat(day)
    except ValueError:
        raise CardError("The Yui note has an invalid date.") from None
    if (not text.strip() or len(text) > 50
            or any(char in text for char in "<>`[]")
            or any(ord(char) < 32 for char in text)):
        raise CardError("The Yui note must contain at most 50 plain-text characters.")
    return day, text


def _png_uri(path):
    """Validate the PNG container before publishing either card."""
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise CardError("A Yui avatar is not a valid PNG image.")
    offset = 8
    chunks = []
    while offset + 12 <= len(data):
        size = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        end = offset + 12 + size
        if end > len(data):
            raise CardError("A Yui avatar PNG is incomplete.")
        payload = data[offset + 8:offset + 8 + size]
        checksum = struct.unpack(">I", data[offset + 8 + size:end])[0]
        if zlib.crc32(kind + payload) & 0xffffffff != checksum:
            raise CardError("A Yui avatar PNG failed its integrity check.")
        if not chunks:
            if kind != b"IHDR" or size != 13:
                raise CardError("A Yui avatar PNG has an invalid header.")
            width, height = struct.unpack(">II", payload[:8])
            if not (0 < width <= 8192 and 0 < height <= 8192):
                raise CardError("A Yui avatar PNG has invalid dimensions.")
        chunks.append(kind)
        offset = end
        if kind == b"IEND":
            break
    if (not chunks or chunks[-1] != b"IEND" or b"IDAT" not in chunks
            or offset != len(data)):
        raise CardError("A Yui avatar PNG is incomplete.")
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def _char_units(char):
    if unicodedata.combining(char) or char in "\ufe0e\ufe0f\u200d":
        return 0
    if unicodedata.east_asian_width(char) in "WF" or ord(char) > 127:
        return 1
    if char in "MW@%&":
        return 1
    if char.isspace():
        return 0.5
    return 0.75


def wrap_text(text, max_units):
    """Wrap by display width, counting Japanese glyphs as full-width cells."""
    nonstarters = "、。，．・：；？！ー〜…‥）］｝〉》」』】〕〗〙〛"
    openers = "（［｛〈《「『【〔〖〘〚"
    lines = []
    current = ""
    units = 0
    for char in text:
        width = _char_units(char)
        if current and units + width > max_units:
            # Keep Japanese closing punctuation with the previous character,
            # and opening brackets with the text that follows them.
            carry = ""
            if len(current) > 1 and (char in nonstarters or current[-1] in openers):
                split = len(current) - 1
                while split > 0 and _char_units(current[split]) == 0:
                    split -= 1
                current, carry = current[:split], current[split:]
            lines.append(current)
            current = carry
            units = sum(_char_units(item) for item in carry)
        current += char
        units += width
    if current:
        lines.append(current)
    return lines


def render_card(day, text, open_uri, closed_uri, *, mobile=False):
    """Return deterministic UTF-8 SVG bytes; no network, clock, or JavaScript."""
    if mobile:
        width, height = 440, 320
        ax, ay, avatar = 22, 42, 96
        bx, by, bw, bh = 20, 157, 400, 141
        tx, ty, size, leading, units = 40, 189, 22, 27, 16
        name_x, name_y, date_x, date_y = 140, 69, 140, 119
        label_x, label_y = 140, 92
    else:
        width, height = 840, 240
        ax, ay, avatar = 28, 61, 140
        bx, by, bw, bh = 192, 59, 622, 160
        tx, ty, size, leading, units = 214, 94, 24, 33, 23
        name_x, name_y, date_x, date_y = 196, 39, 214, 202
        label_x, label_y = 682, 38
    lines = wrap_text(text, units)
    if len(lines) > (4 if mobile else 3):
        raise CardError("The Yui note does not fit the dialogue card.")
    text_lines = "\n".join(
        f'    <tspan x="{tx}" y="{ty + index * leading}">{html.escape(line)}</tspan>'
        for index, line in enumerate(lines)
    )
    cx, cy, radius = ax + avatar // 2, ay + avatar // 2, avatar // 2
    title = html.escape(f"Yui · {day} · {text}")
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description">
  <title id="title">{title}</title>
  <desc id="description">Yui's daily message. Her portrait briefly blinks once every eight seconds. Reduced motion shows the still portrait.</desc>
  <defs>
    <clipPath id="avatar-clip"><circle cx="{cx}" cy="{cy}" r="{radius}" /></clipPath>
  </defs>
  <style>
    text {{ font-family: {FONT}; }}
    .closed {{ opacity: 0; animation: blink 8s linear infinite; }}
    .spark {{ animation: glimmer 5s ease-in-out infinite; }}
    .spark-two {{ animation-delay: -2.2s; }}
    @keyframes blink {{ 0%, 95.99% {{ opacity: 0; }} 96%, 97.74% {{ opacity: 1; }} 97.75%, 100% {{ opacity: 0; }} }}
    @keyframes glimmer {{ 0%, 100% {{ opacity: .22; }} 50% {{ opacity: .65; }} }}
    @media (prefers-reduced-motion: reduce) {{ .closed {{ animation: none; opacity: 0; }} .spark {{ animation: none; opacity: .3; }} }}
  </style>
  <rect x="1" y="1" width="{width - 2}" height="{height - 2}" rx="20" fill="#0d1b2b" stroke="#254f65" />
  <path d="M20 34V20H54 M{width - 54} {height - 20}H{width - 20}V{height - 34}" fill="none" stroke="#69b6cb" stroke-opacity=".55" />
  <path d="M{width - 29} 17l5 5-5 5-5-5z" fill="#d8b975" opacity=".85" />
  <circle cx="{cx}" cy="{cy}" r="{radius + 4}" fill="#102538" stroke="#65b7ca" stroke-opacity=".7" />
  <g clip-path="url(#avatar-clip)">
    <image x="{ax}" y="{ay}" width="{avatar}" height="{avatar}" preserveAspectRatio="xMidYMid slice" href="{open_uri}" />
    <image class="closed" x="{ax}" y="{ay}" width="{avatar}" height="{avatar}" preserveAspectRatio="xMidYMid slice" href="{closed_uri}" />
  </g>
  <circle class="spark" cx="{ax + avatar + 7}" cy="{ay + 16}" r="2.5" fill="#acddeb" opacity=".22" />
  <circle class="spark spark-two" cx="{ax - 5}" cy="{ay + avatar - 17}" r="1.8" fill="#dec489" opacity=".22" />
  <text x="{name_x}" y="{name_y}" fill="#edf7fa" font-size="19" font-weight="600">YUI <tspan fill="#d8b975" font-size="15">/ ユイ</tspan></text>
  <text x="{label_x}" y="{label_y}" fill="#87afbf" font-size="10" letter-spacing="1.3">DAILY INSIGHT</text>
  <rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="15" fill="#13283c" stroke="#284b60" />
  <text id="message" fill="#ecf5fa" font-size="{size}" font-weight="400" xml:space="preserve">
{text_lines}
  </text>
  <text id="date" x="{date_x}" y="{date_y}" fill="#9db7c5" font-size="12">{html.escape(day)} · JST</text>
</svg>
'''
    return svg.encode("utf-8")


def render_yui_cards(content, assets_dir):
    """Prepare both cards completely before any output is changed."""
    day, text = parse_note(content)
    assets = Path(assets_dir)
    open_uri = _png_uri(assets / "yui-avatar-open.png")
    closed_uri = _png_uri(assets / "yui-avatar-closed.png")
    return {
        assets / "yui-dialogue.svg": render_card(day, text, open_uri, closed_uri),
        assets / "yui-dialogue-mobile.svg": render_card(
            day, text, open_uri, closed_uri, mobile=True),
    }


def write_files_safely(outputs):
    """Stage all files, then replace; restore originals if a replacement fails."""
    originals = {}
    staged = {}
    replaced = []
    try:
        for path, data in outputs.items():
            path = Path(path)
            originals[path] = path.read_bytes() if path.exists() else None
            if originals[path] == data:
                continue
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
                staged[path] = Path(handle.name)
                handle.write(data)
        for path, temporary in staged.items():
            os.replace(temporary, path)
            replaced.append(path)
    except OSError:
        for path in reversed(replaced):
            if originals[path] is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(originals[path])
        raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)
    return bool(replaced)


def write_yui_cards(readme_path=DEFAULT_README):
    """Offline entry point: render the existing README note, preserving its date."""
    path = Path(readme_path)
    cards = render_yui_cards(path.read_bytes(), path.parent / "assets")
    return write_files_safely(cards)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readme", type=Path, default=DEFAULT_README)
    args = parser.parse_args(argv)
    try:
        changed = write_yui_cards(args.readme)
    except (CardError, OSError, UnicodeError):
        print("Yui cards could not be rendered safely; check the note and avatar PNGs.",
              file=sys.stderr)
        return 1
    print("Yui cards rendered." if changed else "Yui cards are unchanged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
