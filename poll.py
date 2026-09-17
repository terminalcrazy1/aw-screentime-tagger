"""Screentime poller CLI. Thin entry: builds the app, dispatches commands.

Usage:
    python poll.py            # loop
    python poll.py once       # single pass
    python poll.py recheck YYYY-MM-DD [..]  # redo days
    python poll.py correct --day D --start HH:MM --end HH:MM --rule R [--end-day D] [--note T]
"""
import argparse
import sys

from app import ScreentimeTagger
from config import Config

RULE_HELP = """with_friends: screentime with friends -> non-screentime, incl. violent
extra: program / video / stream given an exception -> non-screentime
educational: program / video / stream was educational -> non-screentime
nonviolent: doing something non-violent -> violent steps down to screentime"""


def _correct_parser():
    ap = argparse.ArgumentParser(
        prog="poll.py correct",
        description="Append one corrections.md entry (explicit user "
                    "statement wins over every auto-label).",
        epilog="rules:\n" + RULE_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--day", default="today",
                    help="today, yesterday, or YYYY-MM-DD (start date)")
    ap.add_argument("--end-day", default=None,
                    help="end date, default = start date")
    ap.add_argument("--start", required=True, help="HH:MM start")
    ap.add_argument("--end", required=True, help="HH:MM end")
    ap.add_argument("--rule", required=True,
                    help="with_friends | extra | educational | nonviolent")
    ap.add_argument("--note", default="", help="optional reminder")
    return ap


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    app = ScreentimeTagger(Config.from_env())
    if not argv:
        app.run_loop()
        return
    cmd, rest = argv[0], argv[1:]
    if cmd == "once":
        app.poll_once()
    elif cmd == "recheck":
        if not rest:
            print("usage: poll.py recheck YYYY-MM-DD [YYYY-MM-DD ...]")
            return
        app.recheck(rest)
    elif cmd == "correct":
        args = _correct_parser().parse_args(rest)
        app.add_correction(args.day, args.start, args.end,
                           args.end_day, args.rule, args.note)
    else:
        print("usage: poll.py [once | recheck YYYY-MM-DD .. | correct --help]")


if __name__ == "__main__":
    main()
