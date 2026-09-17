"""PollState: poll position in state.json. Survives restarts."""
import json
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
        self._data[bucket_id] = {
            "last_id": last_id,
            "updated": datetime.now(timezone.utc).isoformat()}
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except Exception:
            pass
