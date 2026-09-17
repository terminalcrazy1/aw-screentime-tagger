"""Classification: site keys, violent list, and model verdicts.

One cohesive unit: derive the app/site key, check the violent list,
ask the local model. Only load_violent() touches the disk; the caller
(ScreentimeTagger) owns caching and reloads the list on change.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache

from screentime.http import request_json

# --- site keys ---

# Apps treated as web browsers: keyed by website, not application name.
BROWSER_APPS = frozenset({
    "firefox.exe", "chrome.exe", "msedge.exe", "brave.exe",
    "opera.exe", "vivaldi.exe", "safari.exe",
})

# Suffix fragment -> site. Derives the cache/model key for browser windows;
# classification itself is always the model's job.
SITE_TABLE = {
    "youtube": "youtube.com", "twitch": "twitch.tv",
    "netflix": "netflix.com", "tiktok": "tiktok.com",
    "reddit": "reddit.com", "gmail": "mail.google.com",
    "google drive": "drive.google.com", "google docs": "docs.google.com",
    "docs": "docs.google.com", "google calendar": "calendar.google.com",
    "google classroom": "classroom.google.com",
    "google": "google.com", "duckduckgo": "duckduckgo.com",
    "github": "github.com", "stackoverflow": "stackoverflow.com",
    "stack overflow": "stackoverflow.com", "hacker news": "news.ycombinator.com",
    "discord": "discord.com", "twitter": "x.com", "x": "x.com",
    "facebook": "facebook.com", "instagram": "instagram.com",
    "wikipedia": "wikipedia.org", "fandom": "fandom.com",
    "steam community": "steamcommunity.com",
    "steam workshop": "steamcommunity.com",
    "google gemini": "gemini.google.com", "gemini": "gemini.google.com",
}

DOMAIN_RE = re.compile(
    r"([a-z0-9][a-z0-9.-]*\.(?:com|net|org|io|gg|tv|co|dev|app|"
    r"info|us|uk|de|fr|nl|ca|au|it|es|live|online|store|xyz|site))\b")

BROWSER_SUFFIX_RE = re.compile(
    r"\s+[—–-]\s*(mozilla firefox|google chrome|microsoft edge|"
    r"brave|opera|vivaldi|safari)\s*$", re.IGNORECASE)

_SPLIT_RE = re.compile(r"(?:^|\s)(?:-|–|—|\||\bat\b)\s*([^|—–-]+?)\s*$")
_PREFIX_RE = re.compile(r"(.+?)\s+[-–—|]")
_CLEAN_RE = re.compile(r"[^a-z0-9 ]")

NON_LATIN_RE = re.compile("[\u4e00-\u9fff\u3400-\u4dbf\u3040-\u30ff\uac00-\ud7af]")

TAG_RE = re.compile(r"tag:\s*(violent-screentime|screentime|non-screentime)\b")
REASON_PREFIX_RE = re.compile(r"(?i)^.*?reason:\s*")


def _lookup(frag):
    frag = _CLEAN_RE.sub("", (frag or "").lower()).strip()
    if not frag:
        return None
    if frag in SITE_TABLE:
        return SITE_TABLE[frag]
    return SITE_TABLE.get(frag.split(" ")[0])


@lru_cache(maxsize=4096)
def extract_site(title):
    t = (title or "").strip()
    t = BROWSER_SUFFIX_RE.sub("", t).strip()
    if not t:
        return None
    m = DOMAIN_RE.search(t.lower())
    if m:
        host = m.group(1)
        return host[4:] if host.startswith("www.") else host
    m = _SPLIT_RE.search(t)
    if m:
        hit = _lookup(m.group(1))
        if hit:
            return hit
    m = _PREFIX_RE.match(t)
    if m:
        hit = _lookup(m.group(1))
        if hit:
            return hit
    return _lookup(t)


@lru_cache(maxsize=4096)
def target(app, title):
    app_l = (app or "").lower() or "unknown"
    if app_l in BROWSER_APPS:
        site = extract_site(title)
        if site:
            return "site", site
    return "app", app_l


# --- violent list ---

def load_violent(path):
    entries, name, patterns, in_patterns = [], None, [], False
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return []
    for line in lines:
        s = line.strip()
        if s.startswith("## "):
            if name and patterns:
                entries.append({"name": name, "patterns": patterns})
            name, patterns, in_patterns = s[3:].strip(), [], False
        elif s.lower().startswith("patterns:"):
            in_patterns = True
        elif in_patterns and s.startswith("-"):
            patterns.append(s[1:].strip())
        elif s and not s.startswith("#"):
            in_patterns = False
    if name and patterns:
        entries.append({"name": name, "patterns": patterns})
    return entries


def mtime_ns(path):
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return -1


# --- model ---

class Classifier:
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
