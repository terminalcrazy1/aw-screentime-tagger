"""Classifier: violent-list prompt, app/site keys, model verdicts.

Pure decisions — no file I/O. The caller (ScreentimeTagger) handles caching
and reloads the violent list only when the file changes.
"""
from __future__ import annotations

import re

from screentime.classify.sites import NON_LATIN_RE, target
from screentime.classify.violent import load_violent
from screentime.http import request_json

TAG_RE = re.compile(r"tag:\s*(violent-screentime|screentime|non-screentime)\b")
REASON_PREFIX_RE = re.compile(r"(?i)^.*?reason:\s*")


class Classifier:
    # Re-exported so existing callers keep working.
    load_violent = staticmethod(load_violent)
    target = staticmethod(target)

    def __init__(self, model, ollama_url, violent_entries):
        self.model = model
        self.ollama_url = ollama_url.rstrip("/")
        self.violent_entries = violent_entries or []
        self._system = None

    @property
    def system(self):
        if self._system is None:
            self._system = self.build_system()
        return self._system

    def refresh(self, violent_entries):
        """Swap entries if changed; drops the cached system prompt."""
        if violent_entries != self.violent_entries:
            self.violent_entries = violent_entries or []
            self._system = None

    def build_system(self):
        listed = "\n".join(
            "- " + e["name"] + " (matches: " + ", ".join(e.get("patterns", [])) + ")"
            for e in self.violent_entries) or "- (none currently listed)"
        return (
            "You reply only in English, never any other language. "
            "Classify into exactly one tag: violent-screentime, screentime, "
            "non-screentime. In order: "
            "1) violent-screentime ONLY if matching this case-by-case list:\n"
            + listed +
            "\nA browser mention of a listed item does not count. "
            "2) screentime ONLY for: video games; movies, shows, streams, "
            "videos, shortform. "
            "Playing a video game is its own basis for screentime — describe "
            "it as playing, never as watching. Only movies, shows, streams, "
            "videos, and shortform are described as watching. "
            "If the window shows a specific video, episode, channel, or "
            "stream on a video platform, the user IS watching: tag "
            "screentime. Search results, homepages, and bare lists are "
            "browsing (non-screentime). "
            "3) otherwise non-screentime. "
            "Reply exactly one line in English, nothing else (English only, "
            "never Chinese or any other language): "
            "tag:{violent-screentime or screentime or non-screentime} "
            "reason:{brief reason}"
        )

    # -- model --
    def _generate(self, system, prompt, timeout=60):
        res = request_json(
            "POST", self.ollama_url + "/api/generate",
            {"model": self.model, "stream": False,
             "system": system, "prompt": prompt},
            timeout=timeout, retries=1)
        return (res or {}).get("response", "")

    def _ask(self, kind, key):
        text = self._generate(self.system, f"{kind}={key!r}")
        m = TAG_RE.search(text)
        if not m:
            return None
        reason = REASON_PREFIX_RE.sub("", text.strip(), count=1)[:120].strip()
        return m.group(1), reason or "model verdict"

    def _restate_english(self, reason):
        text = self._generate(
            "Restate the user's text in plain English, "
            "under 15 words, no other text.", reason).strip()
        line = text.splitlines()[0].strip()[:120] if text else ""
        if not line or NON_LATIN_RE.search(line):
            return None
        return line

    def decide(self, kind, key):
        """Returns (tag, reason) or None if the model is unreachable."""
        try:
            res = self._ask(kind, key)
        except Exception:
            res = None
        if res is None:
            return None
        if NON_LATIN_RE.search(res[1]):
            try:
                eng = self._restate_english(res[1])
            except Exception:
                eng = None
            if eng:
                res = (res[0], eng)
        return res
