# Violent games — case-by-case list

An application is `violent-screentime` **if and only if** it matches an entry
below. Everything else is decided by the model (game or video/stream →
`screentime`, otherwise `non-screentime`). To add a game, copy one of the
sections: a `## Name` heading plus a `patterns:` bullet list.

## How matching works

The list above is handed to the model as its match vocabulary — the model
applies it, no code matching. Guidance baked into its instructions: an
`.exe`-style pattern means the application itself; a plain name also matches
a window title, except title-only mentions inside a browser or media player
(watching a video *about* a listed game is `screentime`, not violent).
Matching is case-insensitive.

## Rust
patterns:
  - rustclient.exe

## Counter Strike 2
patterns:
  - cs2.exe
  - counter strike
  - counter-strike
  - cs2
