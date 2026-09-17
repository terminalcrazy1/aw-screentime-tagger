"""Shared HTTP helper. One retry/backoff implementation for AW + Ollama."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request


def request_json(method, url, body=None, timeout=60, retries=1,
                 backoff=3.0):
    """Send JSON, return parsed body (or None on empty/404). Retries once."""
    data = json.dumps(body).encode() if body is not None else None
    last = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
        except Exception as e:  # transient network / timeout
            last = e
        if attempt < retries:
            time.sleep(backoff)
    raise last
