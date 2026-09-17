"""CorrectionList: corrections.md time ranges for the prompt-only rules.

An explicit user statement wins over every auto-label. Last entry wins on
overlap. Unknown rules and malformed sections are skipped.
"""
import re
from datetime import datetime

from config import CORRECTION_KINDS, FORCE_NON, DOWNGRADE


def parse_hm(s):
    m = re.match(r"^\s*(\d{1,2}):(\d{2})(?:\s*([ap])\.?\s*m\.?)?\s*$",
                 (s or "").lower())
    if not m:
        raise ValueError(f"bad time: {s!r}, use HH:MM (24h or am/pm)")
    h, mi, ap = int(m.group(1)), int(m.group(2)), m.group(3)
    if ap == "p" and h < 12:
        h += 12
    if ap == "a" and h == 12:
        h = 0
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        raise ValueError(f"bad time: {s!r}")
    return h, mi


def parse_section_head(line):
    from datetime import date as _date, time as _time
    s = (line or "").strip()
    m = re.match(
        r"^##\s+(\d{4}-\d{2}-\d{2})\s+"
        r"(\d{1,2}:\d{2}\s*(?:[ap]\.?m\.?)?)\s*(?:-|–|—|to)\s*"
        r"(\d{4}-\d{2}-\d{2})\s+"
        r"(\d{1,2}:\d{2}\s*(?:[ap]\.?m\.?)?)\s*$", s, re.IGNORECASE)
    try:
        if m:
            h1, mi1 = parse_hm(m.group(2))
            h2, mi2 = parse_hm(m.group(4))
            start = datetime.combine(_date.fromisoformat(m.group(1)),
                                     _time(h1, mi1)).astimezone()
            end = datetime.combine(_date.fromisoformat(m.group(3)),
                                   _time(h2, mi2)).astimezone()
            return (start, end) if end > start else None
        m = re.match(
            r"^##\s+(\d{4}-\d{2}-\d{2})\s+"
            r"(\d{1,2}:\d{2}\s*(?:[ap]\.?m\.?)?)\s*(?:-|–|—|to)\s*"
            r"(\d{1,2}:\d{2}\s*(?:[ap]\.?m\.?)?)\s*$", s, re.IGNORECASE)
        if not m:
            return None
        day = _date.fromisoformat(m.group(1))
        h1, mi1 = parse_hm(m.group(2))
        h2, mi2 = parse_hm(m.group(3))
        start = datetime.combine(day, _time(h1, mi1)).astimezone()
        end = datetime.combine(day, _time(h2, mi2)).astimezone()
    except ValueError:
        return None
    return (start, end) if end > start else None


def resolve_day(s):
    from datetime import date as _date, timedelta as _td
    t = (s or "").strip().lower()
    if t in ("", "today"):
        return _date.today()
    if t == "yesterday":
        return _date.today() - _td(days=1)
    return _date.fromisoformat(t)


class CorrectionList:
    def __init__(self, path):
        self.path = path
        self.entries = self.load()

    def load(self):
        out = []
        try:
            with open(self.path, encoding="utf-8") as f:
                text = f.read()
        except FileNotFoundError:
            return out
        cur = None
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("## "):
                if cur and cur.get("rule"):
                    out.append(cur)
                span = parse_section_head(s)
                cur = {"start": span[0], "end": span[1], "rule": None,
                       "note": ""} if span else None
                continue
            if cur is None:
                continue
            m = re.match(r"^rule:\s*(\S+)", s, re.IGNORECASE)
            if m and m.group(1).lower() in CORRECTION_KINDS:
                cur["rule"] = m.group(1).lower()
                continue
            m = re.match(r"^note:\s*(.*)$", s, re.IGNORECASE)
            if m:
                cur["note"] = m.group(1).strip()[:200]
        if cur and cur.get("rule"):
            out.append(cur)
        return out

    def for_timestamp(self, ts_iso, auto_label):
        """Returns (label, rule) override or (None, None)."""
        try:
            ts = datetime.fromisoformat(str(ts_iso).replace("Z", "+00:00"))
        except Exception:
            return None, None
        hit = None
        for c in self.entries:
            try:
                if c["start"] <= ts < c["end"]:
                    hit = c
            except Exception:
                continue
        if not hit:
            return None, None
        rule = hit["rule"]
        if rule in FORCE_NON:
            return "non-screentime", rule
        if rule in DOWNGRADE:
            return (("screentime", rule) if auto_label == "violent-screentime"
                    else (None, None))
        return None, None

    def append_entry(self, day, start_hm, end_day, end_hm, rule, note=""):
        from datetime import time as _time
        start = datetime.combine(day, _time(*start_hm)).astimezone()
        end = datetime.combine(end_day, _time(*end_hm)).astimezone()
        if end <= start:
            raise ValueError("end must be after start")
        overlap = [c for c in self.entries
                   if c["start"] < end and start < c["end"]]
        if day == end_day:
            head = (f"## {day.isoformat()} {start_hm[0]:02d}:{start_hm[1]:02d}"
                    f"–{end_hm[0]:02d}:{end_hm[1]:02d}")
        else:
            head = (f"## {day.isoformat()} {start_hm[0]:02d}:{start_hm[1]:02d}–"
                    f"{end_day.isoformat()} {end_hm[0]:02d}:{end_hm[1]:02d}")
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(f"\n{head}\nrule: {rule}\n")
            if note:
                f.write(f"note: {note[:200]}\n")
        self.entries = self.load()
        return head[3:], overlap
