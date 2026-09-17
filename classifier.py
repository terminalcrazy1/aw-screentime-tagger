"""Classifier: violent-list prompt, app/site keys, model verdicts.

Pure decisions — no file I/O. The caller (ScreentimeTagger) handles caching.
"""
import json
import re
import time
import urllib.request

from config import LABELS

# Apps treated as web browsers: keyed by website, not application name.
BROWSER_APPS = {"firefox.exe", "chrome.exe", "msedge.exe", "brave.exe",
                "opera.exe", "vivaldi.exe", "safari.exe"}

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
DOMAIN_RES = (r"([a-z0-9][a-z0-9.-]*\.(?:com|net|org|io|gg|tv|co|dev|app|"
              r"info|us|uk|de|fr|nl|ca|au|it|es|live|online|store|xyz|site))\b")

_BROWSER_SUFFIX = (r"\s+[—–-]\s*(mozilla firefox|google chrome|microsoft edge|"
                   r"brave|opera|vivaldi|safari)\s*$")

_NON_LATIN = (r"[\u4e00-\u9fff\u3400-\u4dbf\u3040-\u30ff\uac00-\ud7af]")


class Classifier:
    def __init__(self, model, ollama_url, violent_entries):
        self.model = model
        self.ollama_url = ollama_url.rstrip("/")
        self.violent_entries = violent_entries or []

    # -- violent list --
    @staticmethod
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

    # -- keys --
    @staticmethod
    def extract_site(title):
        t = (title or "").strip()
        t = re.sub(_BROWSER_SUFFIX, "", t, flags=re.IGNORECASE).strip()
        if not t:
            return None
        m = re.search(DOMAIN_RES, t.lower())
        if m:
            host = m.group(1)
            return host[4:] if host.startswith("www.") else host

        def lookup(frag):
            frag = re.sub(r"[^a-z0-9 ]", "", (frag or "").lower()).strip()
            if not frag:
                return None
            if frag in SITE_TABLE:
                return SITE_TABLE[frag]
            return SITE_TABLE.get(frag.split(" ")[0])

        m = re.search(r"(?:^|\s)(?:-|–|—|\||\bat\b)\s*([^|—–-]+?)\s*$", t)
        if m:
            hit = lookup(m.group(1))
            if hit:
                return hit
        m = re.match(r"(.+?)\s+[-–—|]", t)
        if m:
            hit = lookup(m.group(1))
            if hit:
                return hit
        return lookup(t)

    @staticmethod
    def target(app, title):
        app_l = (app or "").lower() or "unknown"
        if app_l in BROWSER_APPS:
            site = Classifier.extract_site(title)
            if site:
                return "site", site
        return "app", app_l

    # -- model --
    def _ask(self, kind, key):
        body = json.dumps({"model": self.model, "stream": False,
                           "system": self.build_system(),
                           "prompt": f"{kind}={key!r}"}).encode()
        req = urllib.request.Request(self.ollama_url + "/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            text = json.loads(r.read().decode()).get("response", "")
        m = re.search(r"tag:\s*(violent-screentime|screentime|non-screentime)\b", text)
        if not m:
            return None
        reason = re.sub(r"(?i)^.*?reason:\s*", "", text.strip(), count=1)[:120].strip()
        return m.group(1), reason or "model verdict"

    def _restate_english(self, reason):
        body = json.dumps({"model": self.model, "stream": False,
                           "system": "Restate the user's text in plain English, "
                                     "under 15 words, no other text.",
                           "prompt": reason}).encode()
        req = urllib.request.Request(self.ollama_url + "/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            text = json.loads(r.read().decode()).get("response", "").strip()
        line = text.splitlines()[0].strip()[:120] if text else ""
        if not line or re.search(_NON_LATIN, line):
            return None
        return line

    def decide(self, kind, key):
        """Returns (tag, reason) or None if the model is unreachable."""
        res = None
        for attempt in (1, 2):
            try:
                res = self._ask(kind, key)
            except Exception:
                res = None
            if res is not None:
                break
            if attempt == 1:
                try:
                    time.sleep(3)
                except Exception:
                    pass
        if res is None:
            return None
        if re.search(_NON_LATIN, res[1]):
            try:
                eng = self._restate_english(res[1])
            except Exception:
                eng = None
            if eng:
                res = (res[0], eng)
        return res
