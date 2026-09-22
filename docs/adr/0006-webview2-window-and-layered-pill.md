# 0006. Draw the window with WebView2 and the pill as a layered Win32 window

- **Status:** Accepted
- **Date:** 2026-09-21

## Context

The settings window was customtkinter and the recording overlay a Tk canvas
with a colour-keyed background: jagged edges, no shadows, and a look far from
current dictation apps.

## Decision

- **Window:** one self-contained HTML page (`livewhisper/ui/index.html`) in
  the system's WebView2 via pywebview, backed by `window.Api`. Loaded as a
  string, not a file path: from a file the page rendered but pywebview's bridge
  was never injected. Light and dark follow Windows.
- **Pill:** a per-pixel-alpha layered window (`UpdateLayeredWindow`) rendered
  with Pillow at 3x supersampling, on its own thread with its own message loop
  (`livewhisper/overlay.py`). `WS_EX_NOACTIVATE` and `MA_NOACTIVATE`: clicking
  it never takes focus from the field being dictated into.

## Consequences

- A modern UI with no web server and no network; about 5 ms per pill frame at
  30 fps, measured to cost nothing in dictation latency.
- WebView2 must be present (all Windows 11, Windows 10 since 2021); the
  installer fetches Microsoft's bootstrapper if not.
- Page globals can collide with pywebview's injected script (a global named
  `keys` silently broke every call); the page avoids generic global names.
- Tk and customtkinter are gone from the app.
