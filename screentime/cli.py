"""Screentime poller CLI. Thin entry: builds the app, dispatches commands.

Usage:
    python poll.py            # loop
    python poll.py once       # single pass
    python poll.py recheck YYYY-MM-DD [..]  # redo days
    python poll.py correct --day D --start HH:MM --end HH:MM --rule R [--end-day D] [--note T]
"""
from __future__ import annotations

import argparse
import sys

from screentime.app import ScreentimeTagger
from screentime.config import Config

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


def _top_parser():
    ap = argparse.ArgumentParser(
        prog="poll.py",
        description="Screentime poller: watch ActivityWatch, tag screentime.")
    ap.add_argument("cmd", nargs="?", default=None,
                    help="once | recheck | correct (empty runs the loop)")
    ap.add_argument("rest", nargs=argparse.REMAINDER,
                    help="args for recheck / correct")
    return ap


def main(argv=None):
    # Parse first so --help never constructs the app (no side effects).
    args = _top_parser().parse_args(sys.argv[1:] if argv is None else argv)
    if args.cmd == "correct" and any(a in ("-h", "--help") for a in args.rest):
        _correct_parser().parse_args(args.rest)  # prints help, exits
        return
    app = ScreentimeTagger(Config.from_env())
    if not args.cmd:
        app.run_loop()
        return
    if args.cmd == "once":
        app.poll_once()
    elif args.cmd == "recheck":
        if not args.rest:
            print("usage: poll.py recheck YYYY-MM-DD [YYYY-MM-DD ...]")
            return
        app.recheck(args.rest)
    elif args.cmd == "correct":
        cargs = _correct_parser().parse_args(args.rest)
        app.add_correction(cargs.day, cargs.start, cargs.end,
                           cargs.end_day, cargs.rule, cargs.note)
    else:
        print("usage: poll.py [once | recheck YYYY-MM-DD .. | correct --help]")


if __name__ == "__main__":
    main()
