"""ActivityWatch HTTP client. All REST traffic lives here."""
from __future__ import annotations

from datetime import datetime

from screentime.http import request_json


class ActivityWatchClient:
    def __init__(self, host):
        self.host = host.rstrip("/")

    def _req(self, method, path, body=None):
        return request_json(method, self.host + path, body,
                            timeout=60, retries=1)

    def buckets(self):
        return self._req("GET", "/api/0/buckets/") or {}

    def window_bucket_id(self):
        for bid, b in self.buckets().items():
            if b.get("type") == "currentwindow":
                return bid
        return None

    def window_events(self, bucket_id, limit=1000):
        return self._req(
            "GET", f"/api/0/buckets/{bucket_id}/events?limit={limit}") or []

    def latest_event(self, bucket_id):
        evs = self.window_events(bucket_id, limit=1)
        return evs[0] if evs else None

    def query_range(self, bucket_id, start_iso, end_iso):
        body = {"timeperiods": [f"{start_iso}/{end_iso}"],
                "query": [f'events = query_bucket("{bucket_id}"); RETURN = events;']}
        res = self._req("POST", "/api/0/query/", body)
        if isinstance(res, list) and res and isinstance(res[0], list):
            return res[0]
        if isinstance(res, dict):
            for v in res.values():
                if isinstance(v, list) and v and isinstance(v[0], list):
                    return v[0]
        return []

    def ensure_labels_bucket(self, bucket_id):
        if self._req("GET", f"/api/0/buckets/{bucket_id}") is None:
            self._req("POST", f"/api/0/buckets/{bucket_id}",
                      {"client": "screentime-poller", "name": bucket_id,
                       "hostname": "", "type": "screentime-labels", "data": {}})

    def post_label(self, bucket_id, timestamp, duration, app, title,
                   label, reason, orig_id):
        return self._req(
            "POST", f"/api/0/buckets/{bucket_id}/events",
            {"timestamp": timestamp, "duration": duration,
             "data": {"app": app, "title": title, "label": label,
                      "reason": reason, "orig_id": orig_id}})

    def delete_event(self, bucket_id, event_id):
        return self._req("DELETE", f"/api/0/buckets/{bucket_id}/events/{event_id}")

    def delete_in_range(self, bucket_id, start_iso, end_iso):
        """Delete copies whose timestamp falls in range. Returns count."""
        start = datetime.fromisoformat(start_iso)
        end = datetime.fromisoformat(end_iso)
        seen, deleted = set(), 0
        while True:
            evs = self.window_events(bucket_id, limit=500)
            fresh = [e for e in evs if e.get("id") not in seen]
            if not fresh:
                break
            for e in fresh:
                seen.add(e.get("id"))
                try:
                    ts = datetime.fromisoformat(
                        str(e.get("timestamp")).replace("Z", "+00:00"))
                except Exception:
                    continue
                if start <= ts < end:
                    self.delete_event(bucket_id, e["id"])
                    deleted += 1
        return deleted
