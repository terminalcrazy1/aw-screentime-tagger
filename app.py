"""ScreentimeTagger: the main class. Owns one client, classifier, cache,
corrections list and poll state; every operation below orchestrates them.
"""
import os
import time
from datetime import datetime, timedelta, timezone

from aw_client import ActivityWatchClient
from cache import DecisionCache
from classifier import Classifier
from config import CORRECTION_KINDS
from corrections import CorrectionList, parse_hm, resolve_day
from load_gate import LoadGate
from state import PollState


class ScreentimeTagger:
    def __init__(self, config):
        self.config = config
        self.client = ActivityWatchClient(config.aw_host)
        self.cache = DecisionCache(config.cache_path, config.cache_max)
        self.corrections = CorrectionList(config.corrections_path)
        self.state = PollState(config.state_path)
        self.gate = LoadGate(config.ollama_url, config.ollama_model,
                             config.max_gpu_util, config.min_free_mb,
                             config.idle_gpu_util)

    def _classifier(self):
        entries = Classifier.load_violent(self.config.violent_path)
        return Classifier(self.config.ollama_model, self.config.ollama_url,
                          entries)

    def _auto(self, app, title):
        """Cache read, else model verdict (stored). Never a correction."""
        kind, key = Classifier.target(app, title)
        hit = self.cache.get(kind, key)
        if hit is not None:
            return hit
        res = self._classifier().decide(kind, key)
        if res is None:
            return "non-screentime", "model unreachable, defaulted"
        self.cache.put(kind, key, res[0], res[1], self.config.ollama_model)
        return res

    def classify_event(self, app, title, ts_iso):
        """Auto-label, then explicit corrections override it."""
        label, reason = self._auto(app, title)
        ov, rule = self.corrections.for_timestamp(ts_iso, label)
        if ov:
            return ov, f"correction:{rule}"
        return label, reason

    def _labels_bucket(self, window_bucket):
        host = window_bucket.split("_", 1)[1] if "_" in window_bucket else "unknown"
        dest = f"screentime-labels_{host}"
        self.client.ensure_labels_bucket(dest)
        return dest

    # -- operations --
    def poll_once(self, verbose=True):
        wb = self.client.window_bucket_id()
        if not wb:
            raise RuntimeError("No aw-watcher-window bucket — is ActivityWatch running?")
        dest = self._labels_bucket(wb)
        last_id = self.state.get_last(wb)
        events = self.client.window_events(wb, limit=1000)
        latest = self.client.latest_event(wb)
        live_id = latest.get("id", -1) if latest else -1
        new = [e for e in events if last_id < e.get("id", -1) < live_id]
        max_id = last_id
        for e in sorted(new, key=lambda x: x.get("id", 0)):
            app = (e.get("data") or {}).get("app", "")
            title = (e.get("data") or {}).get("title", "")
            label, reason = self.classify_event(app, title, e.get("timestamp"))
            print(f"tag:{label} reason:{reason}  [{app} | {title}]", flush=True)
            self.client.post_label(dest, e.get("timestamp"),
                                   e.get("duration", 0), app, title,
                                   label, reason, e.get("id"))
            max_id = max(max_id, e.get("id", max_id))
        self.state.set_last(wb, max_id)
        if verbose:
            print(f"{wb}: {len(new)} new -> {dest}")
        return len(new)

    def run_loop(self, max_passes=None):
        print(f"Polling every {self.config.poll_interval}s. Ctrl+C to stop.",
              flush=True)
        print(f"Load gate: pausing below {self.config.min_free_mb}MiB free "
              f"or at >= {self.config.max_gpu_util}% GPU; model unloaded "
              f"while paused.", flush=True)
        passes = 0
        while True:
            try:
                busy, changed = self.gate.check()
                if busy:
                    if changed:
                        util, free = self.gate.gpu_status()
                        self.gate.unload_model()
                        print(f"pausing: gpu {util}%, {free}MiB free - "
                              f"unloading model until resources free up",
                              flush=True)
                else:
                    if changed:
                        print("load clear, resuming labelling", flush=True)
                    self.poll_once(verbose=False)
            except Exception as ex:
                print(f"poll error: {ex}", flush=True)
            passes += 1
            if max_passes is not None and passes >= max_passes:
                return
            time.sleep(self.config.poll_interval)

    def recheck(self, days):
        from datetime import date as _date
        wb = self.client.window_bucket_id()
        if not wb:
            raise RuntimeError("No aw-watcher-window bucket — is ActivityWatch running?")
        dest = self._labels_bucket(wb)
        kept = self.cache.hand_fixes()
        if os.path.exists(self.config.cache_path):
            os.remove(self.config.cache_path)
        self.cache.load()
        for (kind, key), (label, reason) in kept.items():
            self.cache.put(kind, key, label, reason, "hand-kept")
        if kept:
            print(f"preserved {len(kept)} hand-fixed decisions")
        self.corrections = CorrectionList(self.config.corrections_path)
        if self.corrections.entries:
            print(f"{len(self.corrections.entries)} corrections loaded")
        day_objs = [_date.fromisoformat(d) for d in days]
        all_events = []
        for d in day_objs:
            s, e = self._day_range(d)
            all_events += [(d, ev) for ev in
                           self.client.query_range(wb, s, e)]
        latest = self.client.latest_event(wb)
        live_id = latest.get("id", -1) if latest else -1
        skipped = [ev for _, ev in all_events if ev.get("id", -1) == live_id]
        all_events = [(d, ev) for d, ev in all_events
                      if ev.get("id", -1) != live_id]
        if skipped:
            print("skipped live event (still growing; poll loop gets it later)")
        print(f"{len(all_events)} window events across {[str(d) for d in day_objs]}")
        undecided = []
        for d in day_objs:
            s, e = self._day_range(d)
            deleted = self.client.delete_in_range(dest, s, e)
            n = 0
            for dd, ev in all_events:
                if dd != d:
                    continue
                app = (ev.get("data") or {}).get("app", "")
                title = (ev.get("data") or {}).get("title", "")
                label, reason = self.classify_event(app, title, ev.get("timestamp"))
                if (reason == "model unreachable, defaulted"
                        and f"{app} | {title}" not in undecided):
                    undecided.append(f"{app} | {title}")
                self.client.post_label(dest, ev.get("timestamp"),
                                       ev.get("duration", 0), app, title,
                                       label, reason, ev.get("id"))
                n += 1
            print(f"{d}: deleted {deleted} stale, posted {n} fresh -> {dest}")
        if undecided:
            print(f"UNDECIDED ({len(undecided)}), counted as non-screentime for now:")
            for u in undecided:
                print("  ?", u)
        else:
            print("No undecided windows.")
        try:
            max_id = max(int(ev.get("id", -1)) for _, ev in all_events)
            cur = self.state.get_last(wb)
            self.state.set_last(wb, max(cur, max_id))
            print(f"poll position advanced to event {self.state.get_last(wb)}")
        except Exception as ex:
            print(f"could not advance poll position: {ex}")
        return True

    @staticmethod
    def _day_range(day):
        start = datetime.combine(day, datetime.min.time()).astimezone()
        return start.isoformat(), (start + timedelta(days=1)).isoformat()

    def add_correction(self, day_s, start_s, end_s, end_day_s, rule, note=""):
        try:
            day = resolve_day(day_s)
            end_day = resolve_day(end_day_s) if end_day_s else day
            h1, mi1 = parse_hm(start_s)
            h2, mi2 = parse_hm(end_s)
        except ValueError as ex:
            print(ex, "- aborting")
            return False
        if rule not in CORRECTION_KINDS:
            print(f"bad rule: {rule} - one of {', '.join(CORRECTION_KINDS)}")
            return False
        from datetime import time as _time
        start = datetime.combine(day, _time(h1, mi1)).astimezone()
        end = datetime.combine(end_day, _time(h2, mi2)).astimezone()
        if end <= start:
            print("end must be after start - aborting")
            return False
        overlap = [c for c in self.corrections.entries
                   if c["start"] < end and start < c["end"]]
        if day == end_day:
            head = (f"## {day.isoformat()} {h1:02d}:{mi1:02d}"
                    f"–{h2:02d}:{mi2:02d}")
        else:
            head = (f"## {day.isoformat()} {h1:02d}:{mi1:02d}–"
                    f"{end_day.isoformat()} {h2:02d}:{mi2:02d}")
        with open(self.config.corrections_path, "a", encoding="utf-8") as f:
            f.write(f"\n{head}\nrule: {rule}\n")
            if note:
                f.write(f"note: {note[:200]}\n")
        self.corrections = CorrectionList(self.config.corrections_path)
        print(f"saved: {head[3:]} rule={rule}")
        if overlap:
            print(f"note: overlaps {len(overlap)} existing entr(y/ies) - last entry wins")
        print("applies to new events immediately; run recheck for past days")
        return True
