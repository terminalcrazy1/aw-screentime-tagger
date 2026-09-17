# Screentime poller

Watches ActivityWatch's window bucket, classifies each finished event as
`violent-screentime` / `screentime` / `non-screentime`, prints
`tag:{class} reason:{reason}`, stores a copy in `screentime-labels_<host>`.

Keys are applications (`spotify.exe`) or, for browser windows, website
top-level URLs (`youtube.com`). Titles are never used. Decisions live in
`cache.md`, one section per key — edit by hand, corrections stick.

Layout (`screentime/` package, `poll.py` is a thin entry): `cli.py`
dispatches to `app.ScreentimeTagger`, which owns `config.Config`,
`aw.ActivityWatchClient`, `classify.Classifier`, `store.DecisionCache`,
`store.CorrectionList`, `store.PollState`, and `gate.LoadGate`.
Shared HTTP retries live in `http.py`. Pure-function tests in `tests/`.

Hierarchy: `violent-screentime` if matching `violent.md` (model-applied) >
`screentime` for games, movies, shows, streams, videos, shortform >
`non-screentime` otherwise. Local model only (`qwen2.5:7b` via Ollama).

```powershell
python poll.py                                                            # loop
python poll.py once                                                       # single pass
python poll.py recheck 2026-09-06 2026-09-07                              # redo days
python poll.py correct --day today --start 20:00 --end 21:30 --rule with_friends --note "..."
powershell -ExecutionPolicy Bypass -File install.ps1                      # startup install
```

Gaming guard: each pass checks free VRAM and GPU load. Below
`AW_MIN_FREE_MB` free (default 5500, i.e. a heavy game resident) or
at/above `AW_MAX_GPU_UTIL` (default 40), the tagger simply pauses —
position doesn't advance, the model is unloaded, and it catches up
naturally once resources are free. Resume needs both genuinely idle:
VRAM back *and* GPU at/below `AW_IDLE_GPU_UTIL` (default 10); the band
in between holds last state so borderline readings can't flap it.
Manual `once`/`recheck` always run immediately.

## Phase 2: the auditor (`audit.py`, all logic inside)

Every night at 00:00 ("Screentime Auditor" scheduled task), Mistral Small
reviews all cache decisions newer than the last audit and writes any
alterations straight into `cache.md`, journaling previous values to
`audit_journal.json`, plus a human report in `audit.md`:

```powershell
python audit.py                 # review + apply + journal
python audit.py --dry-run       # show alterations, change nothing
python audit.py --limit N       # cap verdicts (default 300)
python audit.py --batch N       # verdicts per call (default 10)
python audit.py revert          # undo the last applied alterations
```

Needs `MISTRAL_API_KEY`. Report-only failures never advance the audit
position, so failed verdicts retry next run.

Rules for `--rule`: `with_friends`, `extra`, `educational` force
non-screentime; `nonviolent` steps violent down to screentime.
`--day` takes today, yesterday, or YYYY-MM-DD; `--end-day` defaults to it.
Full usage: `python poll.py correct --help`.

Dashboard (aw-dashboard Query explorer):

```
events = query_bucket(find_bucket("screentime-labels_"));
afk = query_bucket(find_bucket("aw-watcher-afk_"));
not_afk = filter_keyvals(afk, "status", ["not-afk"]);
events = filter_period_intersect(events, not_afk);
events = merge_events_by_keys(events, ["label"]);
RETURN = sort_by_duration(events);
```
