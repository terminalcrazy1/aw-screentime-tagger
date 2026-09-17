"""DecisionCache: cache.md, one section per app/site key.

Authoritative store. Hand edits win on next load; malformed sections are
skipped. Sections whose reason contains 'hand ' are user-approved.
"""
import os
import re
from datetime import datetime, timezone

from config import LABELS


class DecisionCache:
    def __init__(self, path, max_entries=5000):
        self.path = path
        self.max_entries = max_entries
        self._data = {}
        self.load()

    def load(self):
        self._data = {}
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
            m = re.match(r"^##\s+(app|site):\s*(.+?)\s*$", s)
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
        while len(self._data) > self.max_entries:
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
                    f.write("# Classification decisions\n\n_One section per "
                            "application or website. Edit tag:/reason: by hand; "
                            "corrections stick._\n")
                f.write(f"\n## {kind}: {key}\ntag: {label}\nreason: {reason}\n"
                        f"decided: {datetime.now(timezone.utc).isoformat()}\n"
                        f"model: {model}\n")
        except Exception:
            pass

    def hand_fixes(self):
        return {k: v for k, v in self._data.items() if "hand " in (v[1] or "")}

    def _rewrite(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("# Classification decisions\n\n_One section per "
                        "application or website. Edit tag:/reason: by hand; "
                        "corrections stick._\n")
                for (kind, key), (label, reason) in self._data.items():
                    f.write(f"\n## {kind}: {key}\ntag: {label}\nreason: {reason}\n"
                            f"decided: kept\nmodel: mixed\n")
            os.replace(tmp, self.path)
        except Exception:
            pass
