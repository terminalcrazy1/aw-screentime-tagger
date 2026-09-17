"""Pure-function smoke tests. Stdlib only: python -m unittest discover -s tests."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from screentime.classify.sites import extract_site, target
from screentime.classify.violent import load_violent
from screentime.store.corrections import (
    CorrectionList, parse_hm, parse_section_head, resolve_day,
)


class TestSites(unittest.TestCase):
    def test_target_app(self):
        self.assertEqual(target("spotify.exe", "Music"), ("app", "spotify.exe"))

    def test_target_browser_site(self):
        self.assertEqual(
            target("firefox.exe", "Some Video - YouTube — Mozilla Firefox"),
            ("site", "youtube.com"))

    def test_target_browser_no_site(self):
        self.assertEqual(
            target("chrome.exe", "")[0], "app")

    def test_extract_domain(self):
        self.assertEqual(extract_site("mypage https://example.com/x"), "example.com")

    def test_extract_www_stripped(self):
        self.assertEqual(extract_site("www.github.com"), "github.com")


class TestViolent(unittest.TestCase):
    def test_load(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                         encoding="utf-8") as f:
            f.write("# t\n\n## Rust\npatterns:\n  - rustclient.exe\n")
            path = f.name
        try:
            entries = load_violent(path)
            self.assertEqual(entries,
                             [{"name": "Rust", "patterns": ["rustclient.exe"]}])
        finally:
            os.unlink(path)

    def test_missing(self):
        self.assertEqual(load_violent("/nonexistent/violent.md"), [])


class TestCorrections(unittest.TestCase):
    def test_parse_hm(self):
        self.assertEqual(parse_hm("20:00"), (20, 0))
        self.assertEqual(parse_hm("8:30 pm"), (20, 30))
        with self.assertRaises(ValueError):
            parse_hm("nope")

    def test_section_head(self):
        span = parse_section_head("## 2026-09-06 20:00–21:30")
        self.assertIsNotNone(span)
        self.assertLess(span[0], span[1])
        self.assertIsNone(parse_section_head("## garbage"))

    def test_resolve_day(self):
        from datetime import date, timedelta
        self.assertEqual(resolve_day("today"), date.today())
        self.assertEqual(resolve_day("yesterday"), date.today() - timedelta(days=1))

    def test_override_last_wins(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                         encoding="utf-8") as f:
            f.write("# c\n\n## 2026-09-06 20:00–21:30\nrule: with_friends\n")
            path = f.name
        try:
            from datetime import timedelta
            cl = CorrectionList(path)
            start = cl.entries[0]["start"]
            inside = (start + timedelta(minutes=15)).isoformat()
            label, rule = cl.for_timestamp(inside, "violent-screentime")
            self.assertEqual((label, rule), ("non-screentime", "with_friends"))
            self.assertEqual(
                cl.for_timestamp("2026-09-06T22:00:00-04:00", "screentime"),
                (None, None))
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
