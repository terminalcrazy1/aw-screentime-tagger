"""PollState: poll position in state.json. Survives restarts."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone


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
