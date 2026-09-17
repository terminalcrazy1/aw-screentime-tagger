"""THE AUDITOR. Nightly Mistral review of new cache.md decisions.

Usage:
    python audit.py                  # review + apply + journal
    python audit.py --dry-run        # show alterations without applying
    python audit.py --limit N        # cap verdicts (default 300)
    python audit.py --batch N        # verdicts per API call (default 10)
    python audit.py --all            # include hand-fixed entries too
    python audit.py revert           # undo the last applied alterations

All logic lives in this file. Needs MISTRAL_API_KEY. Writes audit.md
(report) and audit_journal.json (revert data). Never invents entries.
"""
import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(BASE_DIR, "cache.md")
STATE_PATH = os.path.join(BASE_DIR, "state.json")
JOURNAL_PATH = os.path.join(BASE_DIR, "audit_journal.json")
REPORT_PATH = os.path.join(BASE_DIR, "audit.md")

REVIEW_MODEL = os.environ.get("MISTRAL_REVIEW_MODEL", "mistral-small-latest")
LABELS = ("violent-screentime", "screentime", "non-screentime")
TOKENS = {"in": 0, "out": 0}

_REVIEW_SYSTEM = (
    "Audit screentime labels, in order: violent-screentime ONLY for Rust, "
    "Counter Strike 2 (an exe named for one counts, e.g. rustclient.exe IS "
    "Rust; a browser mention doesn't count); screentime ONLY for played "
    "games and watched movies/shows/streams/videos/shortform (playing is "
    "never watching); else non-screentime. "
    "Reply one line per item, nothing else: `<n> AGREE` or "
    "`<n> DISAGREE tag:X reason:Y`."
)


def _call(messages, max_tokens):
    import re as _re
    api_key = os.environ.get("MISTRAL_API_KEY", "")
    if not api_key:
        return None, "MISTRAL_API_KEY is not set"
    body = json.dumps({"model": REVIEW_MODEL, "temperature": 0.0,
                       "max_tokens": max_tokens, "messages": messages}).encode()
    try:
        req = urllib.request.Request(
            "https://api.mistral.ai/v1/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + api_key})
        with urllib.request.urlopen(req, timeout=60) as r:
            outer = json.loads(r.read().decode())
        try:
            use = outer.get("usage") or {}
            TOKENS["in"] += int(use.get("prompt_tokens", 0))
            TOKENS["out"] += int(use.get("completion_tokens", 0))
        except Exception:
            pass
        return outer["choices"][0]["message"]["content"].strip(), ""
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return None, "Mistral API rejected the key (401)"
        return None, f"Mistral API error {e.code}"
    except Exception as ex:
        return None, f"request failed: {ex}"[:120]


def _parse_batch(text, items):
    import re as _re
    out = [None] * len(items)
    for ln in (text or "").splitlines():
        m = _re.match(r"(\d+)[.)]?\s+(?:\d+[.)]?\s+)?AGREE\s*$",
                      ln.strip(), _re.IGNORECASE)
        if m:
            i = int(m.group(1)) - 1
            if 0 <= i < len(items):
                out[i] = ("agree", items[i][2], items[i][3])
            continue
        m = _re.match(
            r"(\d+)[.)]?\s+(?:\d+[.)]?\s+)?DISAGREE\s+tag:\s*"
            r"(violent-screentime|screentime|non-screentime)\b"
            r"\s*reason:(.+)$", ln.strip(), _re.IGNORECASE)
        if m:
            i = int(m.group(1)) - 1
            if 0 <= i < len(items):
                if m.group(2) == items[i][2]:
                    out[i] = ("agree", items[i][2], items[i][3])
                else:
                    out[i] = ("disagree", m.group(2),
                              m.group(3).strip()[:200])
    return out


def _review_single(kind, key, tag, reason):
    import re as _re
    text, err = _call(
        [{"role": "system", "content": _REVIEW_SYSTEM},
         {"role": "user",
          "content": f"1. [{kind}] {key} | was: {tag} ({reason})"}],
        120)
    if err:
        return "error", tag, err
    if text.upper().startswith("AGREE") or _re.match(
            r"1[\s.)]+AGREE", text.upper()):
        return "agree", tag, reason
    m = _re.search(
        r"DISAGREE\s+tag:\s*(violent-screentime|screentime|non-screentime)\b"
        r"\s*reason:(.+)$", text, _re.IGNORECASE | _re.DOTALL)
    if m:
        if m.group(1) == tag:
            return "agree", tag, reason
        return "disagree", m.group(1), m.group(2).strip()[:200]
    return "error", tag, f"unparseable reply: {text[:120]}"


def review_batch(items):
    """items: [(kind, key, tag, reason)]. Returns [(verdict, tag, reason)]."""
    lines = [f"{i}. [{k}] {key} | was: {t} ({r})"
             for i, (k, key, t, r) in enumerate(items, 1)]
    text, err = _call(
        [{"role": "system", "content": _REVIEW_SYSTEM},
         {"role": "user", "content": "Audit these:\n" + "\n".join(lines)}],
        min(2000, 40 + 30 * len(items)))
    if err:
        return [("error", t, err) for (_, _, t, _) in items]
    out = _parse_batch(text, items)
    for i, (k, key, t, r) in enumerate(items):
        if out[i] is None:
            v, t2, r2 = _review_single(k, key, t, r)
            out[i] = (v, t2, r2)
    return out


def load_sections():
    import re as _re
    out = []
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return out
    kind = key = None
    rec = None
    for line in text.splitlines():
        s = line.strip()
        m = _re.match(r"^##\s+(app|site):\s*(.+?)\s*$", s)
        if m:
            if rec and rec.get("tag") in LABELS:
                out.append(rec)
            kind, key = m.group(1), m.group(2).lower()
            rec = {"kind": kind, "key": key, "tag": None, "reason": "",
                   "decided": "", "reviewed": ""}
            continue
        if rec is None:
            continue
        if s.startswith("tag:"):
            rec["tag"] = s[4:].strip()
        elif s.startswith("reason:"):
            rec["reason"] = s[7:].strip()
        elif s.startswith("decided:"):
            rec["decided"] = s[8:].strip()
        elif s.startswith("reviewed:"):
            rec["reviewed"] = s[9:].strip()
    if rec and rec.get("tag") in LABELS:
        out.append(rec)
    return out


def mark_reviewed(headings, when):
    """Stamp `reviewed:` on the given `## kind: key` headings (if absent)."""
    import re as _re
    with open(CACHE_PATH, encoding="utf-8") as f:
        text = f.read()
    parts = _re.split(r'(?m)^(?=## )', text)
    want = set(headings)
    n = 0
    for i, s in enumerate(parts):
        if not s.startswith("## "):
            continue
        head = s.splitlines()[0].strip()
        if head not in want:
            continue
        if _re.search(r'(?m)^reviewed:\s*\S', s):
            continue
        parts[i] = s.rstrip("\n") + f"\nreviewed: {when}\n"
        n += 1
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        f.write(''.join(parts))
    return n


def apply_alterations(changes):
    """Rewrite tag:/reason: lines for the given headings. Returns count."""
    import re as _re
    with open(CACHE_PATH, encoding="utf-8") as f:
        text = f.read()
    parts = _re.split(r'(?m)^(?=## )', text)
    by_head = {c["heading"]: c for c in changes}
    n = 0
    for i, s in enumerate(parts):
        if not s.startswith("## "):
            continue
        head = s.splitlines()[0].strip()
        if head not in by_head:
            continue
        c = by_head[head]
        s = _re2.sub(r'(?m)^tag:\s*\S+', 'tag: ' + c["new_tag"], s, count=1)
        s = _re2.sub(r'(?m)^reason:\s*.+$', 'reason: ' + c["new_reason"], s,
                   count=1)
        parts[i] = s
        n += 1
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        f.write(''.join(parts))
    return n


def cmd_review(args):
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        state = {}
    recs = load_sections()
    # Only unreviewed entries are ever processed.
    todo = [r for r in recs
            if not r.get("reviewed")
            and ("hand " not in (r["reason"] or "") or args.all)]
    if args.limit and len(todo) > args.limit:
        todo = todo[:args.limit]
        truncated = True
    else:
        truncated = False
    if not todo:
        print("nothing new to review")
        return
    size = max(1, args.batch)
    chunks = [todo[i:i + size] for i in range(0, len(todo), size)]
    agree, alterations, errors, settled = 0, [], [], []
    done = 0
    for chunk in chunks:
        items = [(r["kind"], r["key"], r["tag"], r["reason"]) for r in chunk]
        res = review_batch(items)
        if res and res[0][0] == "error" and "429" in (res[0][2] or ""):
            for wait in (10, 30):
                print(f"rate-limited, waiting {wait}s", flush=True)
                time.sleep(wait)
                res = review_batch(items)
                if not (res and res[0][0] == "error" and "429" in (res[0][2] or "")):
                    break
        for r, (v, t, rsn) in zip(chunk, res):
            done += 1
            print(f"[{done}/{len(todo)}] {r['kind']}: {r['key']} -> {v}",
                  flush=True)
            if v == "agree":
                agree += 1
                settled.append(f"## {r['kind']}: {r['key']}")
            elif v == "disagree":
                alterations.append({
                    "heading": f"## {r['kind']}: {r['key']}",
                    "old_tag": r["tag"], "old_reason": r["reason"],
                    "new_tag": t, "new_reason": rsn})
            else:
                errors.append((r, rsn))
        time.sleep(1.2)
    now = datetime.now(timezone.utc)
    lines = [f"# Audit {now.date().isoformat()} ({REVIEW_MODEL})", "",
             f"Reviewed {len(todo)} decisions"
             + (f" (truncated, cap {args.limit})" if truncated else "")
             + f". {agree} agree, {len(alterations)} to alter, "
             f"{len(errors)} errors.",
             f"Tokens this run: {TOKENS['in']} in / {TOKENS['out']} out.", "",
             "Only entries without a `reviewed:` stamp were processed.", ""]
    if alterations:
        lines += ["## Alterations"
                  + (" (APPLIED)" if not args.dry_run else " (dry run, not applied)"), ""]
        for c in alterations:
            lines += [f"- `{c['heading']}` {c['old_tag']} → **{c['new_tag']}**: "
                      f"{c['new_reason']}", ""]
    if errors:
        lines += ["## Errors", ""]
        for r, rsn in errors:
            lines += [f"- `{r['kind']}: {r['key']}`: {rsn}", ""]
    if args.dry_run:
        print("\n".join(lines))
        print("dry run: cache.md untouched, journal untouched")
        return
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    with open(JOURNAL_PATH, "w", encoding="utf-8") as f:
        json.dump({"applied_at": now.isoformat(), "model": REVIEW_MODEL,
                   "changes": alterations}, f, indent=2)
    n = apply_alterations(alterations) if alterations else 0
    print(f"applied {n} alterations (journal saved for revert)")
    marked = mark_reviewed(
        settled + [c["heading"] for c in alterations], now.date().isoformat())
    print(f"marked {marked} entries reviewed")
    if not errors:
        state["last_audit"] = now.isoformat()
        try:
            with open(STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
        except Exception as ex:
            print(f"could not save state: {ex}")
    else:
        print("errors present - last_audit left unchanged so failures retry next run")
    print(f"done: {agree} agree, {len(alterations)} altered, "
          f"{len(errors)} errors -> audit.md")


def cmd_revert():
    try:
        with open(JOURNAL_PATH, encoding="utf-8") as f:
            journal = json.load(f)
    except FileNotFoundError:
        print("no journal found - nothing to revert")
        return
    changes = journal.get("changes", [])
    if not changes:
        print("journal is empty - nothing to revert")
        return
    import re as _re
    with open(CACHE_PATH, encoding="utf-8") as f:
        text = f.read()
    parts = _re.split(r'(?m)^(?=## )', text)
    by_head = {c["heading"]: c for c in changes}
    n = 0
    for i, s in enumerate(parts):
        if not s.startswith("## "):
            continue
        head = s.splitlines()[0].strip()
        if head not in by_head:
            continue
        c = by_head[head]
        cur = _re2.search(r'(?m)^tag:\s*(\S+)', s)
        if cur and cur.group(1) == c["new_tag"]:
            s = _re2.sub(r'(?m)^tag:\s*\S+', 'tag: ' + c["old_tag"], s, count=1)
            s = _re2.sub(r'(?m)^reason:\s*.+$', 'reason: ' + c["old_reason"], s,
                       count=1)
            s = _re2.sub(r'(?m)^reviewed:\s*\S.*\n?', '', s)
            parts[i] = s
            n += 1
        else:
            print(f"skipped {head}: no longer holds the applied verdict")
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        f.write(''.join(parts))
    os.remove(JOURNAL_PATH)
    print(f"reverted {n} of {len(changes)} alterations (journal cleared)")


def main():
    import argparse as _ap
    if len(sys.argv) > 1 and sys.argv[1] == "revert":
        cmd_revert()
        return
    ap = _ap.ArgumentParser(
        prog="audit.py",
        description="Nightly Mistral review of new cache.md decisions. "
                    "Applies alterations, journals them for revert.")
    ap.add_argument("--dry-run", action="store_true",
                    help="show alterations without applying")
    ap.add_argument("--all", action="store_true",
                    help="include hand-fixed entries too")
    ap.add_argument("--limit", type=int, default=300,
                    help="max verdicts per run (default 300, 0 = no cap)")
    ap.add_argument("--batch", type=int, default=10,
                    help="verdicts per API call (default 10)")
    cmd_review(ap.parse_args(sys.argv[1:]))


if __name__ == "__main__":
    main()
