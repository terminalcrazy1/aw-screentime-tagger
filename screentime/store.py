"""Persistence: decision cache, correction list, and poll state.

All file-backed stores live here: cache.md (model verdicts),
corrections.md (explicit time-range overrides), state.json (poll position).
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache

from screentime.config import CORRECTION_KINDS, DOWNGRADE, FORCE_NON, LABELS

# --- decision cache ---

SECTION_RE = re.compile(r"^##\s+(app|site):\s*(.+?)\s*$")
HEADER = ("# Classification decisions\n\n_One section per "
          "application or website. Edit tag:/reason: by hand; "
          "corrections stick._\n")


class DecisionCache:
    def __init__(self, path, max_entries=5000):
        self.path = path
        self.max_entries = max_entries
        self._data = {}
        self._appends = 0
        self.load()

    def load(self):
        self._data = {}
        self._appends = 0
        try:
            with open(self.path, encoding="utf-8") as f:
                text = f.read()
        except FileNotFoundError:
            return self._data
        kind = key = None
        label = reason = None

        def flush():
            if kind and key and label in LABELS:
                self._data[(kind, key)] = (label, reason or "")

        for line in text.splitlines():
            s = line.strip()
            m = SECTION_RE.match(s)
            if m:
                flush()
                kind, key, label, reason = m.group(1), m.group(2).lower(), None, None
                continue
            if kind is None:
                continue
            if s.startswith("tag:"):
                label = s[4:].strip()
            elif s.startswith("reason:"):
                reason = s[7:].strip()
        flush()
        if len(self._data) > self.max_entries:
            for k in list(self._data)[: len(self._data) - self.max_entries]:
                del self._data[k]
            self._rewrite()
        return self._data

    def __len__(self):
        return len(self._data)

    def __contains__(self, key):
        return key in self._data

    def get(self, kind, key):
        return self._data.get((kind, key))

    def put(self, kind, key, label, reason, model=""):
        self._data[(kind, key)] = (label, reason)
        try:
            new_file = not os.path.exists(self.path)
            with open(self.path, "a", encoding="utf-8") as f:
                if new_file:
                    f.write(HEADER)
                f.write(f"\n## {kind}: {key}\ntag: {label}\nreason: {reason}\n"
                        f"decided: {datetime.now(timezone.utc).isoformat()}\n"
                        f"model: {model}\n")
            self._appends += 1
            self._maybe_compact()
        except Exception:
            pass

    def hand_fixes(self):
        return {k: v for k, v in self._data.items() if "hand " in (v[1] or "")}

    def _maybe_compact(self):
        # Appends duplicate older sections; rewrite occasionally to bound
        # file growth instead of letting it grow without limit.
        if self._appends >= 500:
            self._rewrite()
            self._appends = 0

    def _rewrite(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(HEADER)
                for (kind, key), (label, reason) in self._data.items():
                    f.write(f"\n## {kind}: {key}\ntag: {label}\nreason: {reason}\n"
                            f"decided: kept\nmodel: mixed\n")
            os.replace(tmp, self.path)
        except Exception:
            pass


# --- corrections ---

HM_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})(?:\s*([ap])\.?\s*m\.?)?\s*$")
RANGE_TWO_DAY_RE = re.compile(
    r"^##\s+(\d{4}-\d{2}-\d{2})\s+"
    r"(\d{1,2}:\d{2}\s*(?:[ap]\.?m\.?)?)\s*(?:-|–|—|to)\s*"
    r"(\d{4}-\d{2}-\d{2})\s+"
    r"(\d{1,2}:\d{2}\s*(?:[ap]\.?m\.?)?)\s*$", re.IGNORECASE)
RANGE_ONE_DAY_RE = re.compile(
    r"^##\s+(\d{4}-\d{2}-\d{2})\s+"
    r"(\d{1,2}:\d{2}\s*(?:[ap]\.?m\.?)?)\s*(?:-|–|—|to)\s*"
    r"(\d{1,2}:\d{2}\s*(?:[ap]\.?m\.?)?)\s*$", re.IGNORECASE)
RULE_RE = re.compile(r"^rule:\s*(\S+)", re.IGNORECASE)
NOTE_RE = re.compile(r"^note:\s*(.*)$", re.IGNORECASE)


@lru_cache(maxsize=256)
def parse_hm(s):
    m = HM_RE.match((s or "").lower())
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
    s = (line or "").strip()
    try:
        m = RANGE_TWO_DAY_RE.match(s)
        if m:
            h1, mi1 = parse_hm(m.group(2))
            h2, mi2 = parse_hm(m.group(4))
            start = datetime.combine(date.fromisoformat(m.group(1)),
                                     time(h1, mi1)).astimezone()
            end = datetime.combine(date.fromisoformat(m.group(3)),
                                   time(h2, mi2)).astimezone()
            return (start, end) if end > start else None
        m = RANGE_ONE_DAY_RE.match(s)
        if not m:
            return None
        day = date.fromisoformat(m.group(1))
        h1, mi1 = parse_hm(m.group(2))
        h2, mi2 = parse_hm(m.group(3))
        start = datetime.combine(day, time(h1, mi1)).astimezone()
        end = datetime.combine(day, time(h2, mi2)).astimezone()
    except ValueError:
        return None
    return (start, end) if end > start else None


def resolve_day(s):
    t = (s or "").strip().lower()
    if t in ("", "today"):
        return date.today()
    if t == "yesterday":
        return date.today() - timedelta(days=1)
    return date.fromisoformat(t)


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
            m = RULE_RE.match(s)
            if m and m.group(1).lower() in CORRECTION_KINDS:
                cur["rule"] = m.group(1).lower()
                continue
            m = NOTE_RE.match(s)
            if m:
                cur["note"] = m.group(1).strip()[:200]
        if cur and cur.get("rule"):
            out.append(cur)
        out.sort(key=lambda c: c["start"])
        return out

    def for_timestamp(self, ts_iso, auto_label):
        """Returns (label, rule) override or (None, None). Last entry wins."""
        try:
            ts = datetime.fromisoformat(str(ts_iso).replace("Z", "+00:00"))
        except Exception:
            return None, None
        for c in reversed(self.entries):  # sorted: last match wins, early exit
            try:
                if c["start"] <= ts < c["end"]:
                    rule = c["rule"]
                    if rule in FORCE_NON:
                        return "non-screentime", rule
                    if rule in DOWNGRADE:
                        if auto_label == "violent-screentime":
                            return "screentime", rule
                        return None, None
                    return None, None
            except Exception:
                continue
        return None, None

    def append_entry(self, day, start_hm, end_day, end_hm, rule, note=""):
        start = datetime.combine(day, time(*start_hm)).astimezone()
        end = datetime.combine(end_day, time(*end_hm)).astimezone()
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


# --- poll state ---

class PollState:
    def __init__(self, path):
        self.path = path
        self._data = {}
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                self._data = json.load(f)
        except Exception:
            self._data = {}
        return self._data

    def get_last(self, bucket_id):
        return self._data.get(bucket_id, {}).get("last_id", -1)

    def set_last(self, bucket_id, last_id):
        if self._data.get(bucket_id, {}).get("last_id") == last_id:
            return  # skip redundant writes when nothing advanced
        self._data[bucket_id] = {
            "last_id": last_id,
            "updated": datetime.now(timezone.utc).isoformat()}
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            pass
