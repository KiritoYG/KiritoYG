"""Decide whether a scheduled Yui run needs a new message, without API calls."""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from yui_card import CardError, parse_note

JST = timezone(timedelta(hours=9))
README_PATH = Path(__file__).with_name("README.md")


class ScheduleError(ValueError):
    """A safe, public explanation for invalid schedule state."""


def needs_update(readme_path, event_name, now=None):
    """Manual runs regenerate; scheduled runs skip a note already dated today."""
    if event_name not in ("schedule", "workflow_dispatch"):
        raise ScheduleError("Unsupported workflow event.")
    note_date, _ = parse_note(Path(readme_path).read_bytes())
    now = now or datetime.now(JST)
    if now.tzinfo is None:
        raise ScheduleError("The current time must include a timezone.")
    current = now.astimezone(JST)
    today = current.date().isoformat()
    if note_date > today:
        raise ScheduleError("README's Yui note is dated in the future.")
    if event_name == "workflow_dispatch":
        return True
    # A delayed retry from yesterday must not create today's note overnight.
    if current.hour < 9:
        return False
    return note_date != today


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readme", type=Path, default=README_PATH)
    parser.add_argument("--event", choices=("schedule", "workflow_dispatch"), required=True)
    args = parser.parse_args(argv)
    try:
        required = needs_update(args.readme, args.event)
    except ScheduleError as error:
        print("Yui precheck failed: " + str(error), file=sys.stderr)
        return 1
    except (CardError, OSError, UnicodeError, ValueError):
        print("Yui precheck failed: README must contain one valid dated Yui note.",
              file=sys.stderr)
        return 1
    # This is the only successful output; the workflow appends it to GITHUB_OUTPUT.
    print("needs_update=" + str(required).lower())
    return 0


if __name__ == "__main__":
    sys.exit(main())
