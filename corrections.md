# Corrections — time periods that met the prompt-only rules

The classifier cannot detect these on its own; your explicit statement wins
over every auto-label. Add sections below by hand, or run `poll.py correct`
and answer its prompts (it resolves today/yesterday to exact dates).

Format per section (times are local, 24-hour or with am/pm).
Single-day shorthand, or full datetimes on both ends for multi-day spans
(overnight included — the end just has to be after the start):

```
## YYYY-MM-DD 20:00–21:30
rule: with_friends
note: Sam and Jo over, Rust on in the background
```

Rules and their effects (applied after the auto-label; last entry wins on
overlap):

- `with_friends` — screentime with friends: everything in the span counts
  as non-screentime, including violent games.
- `extra` — the program / video / stream was given an exception:
  non-screentime.
- `educational` — the program / video / stream was educational:
  non-screentime.
- `nonviolent` — doing something non-violent: violent-screentime steps down
  to regular screentime; everything else unchanged.

