"""Browser/site key derivation. Pure functions, no I/O."""
from __future__ import annotations

import re
from functools import lru_cache

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
