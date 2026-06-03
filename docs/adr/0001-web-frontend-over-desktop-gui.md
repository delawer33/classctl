# ADR 0001: Web frontend over desktop GUI

## Status
Accepted

## Context
The spec requires a GUI. The natural Python options were a desktop toolkit (PyQt6) or a web frontend (FastAPI + HTML/JS). The tool needs to display live output from up to 35 concurrent SSH sessions, which maps well to streaming UI patterns.

## Decision
Use a web frontend: FastAPI backend with WebSockets for live output streaming, served on localhost. The operator opens a browser to `localhost:PORT`. The CLI (if implemented) shares the same Python core.

## Consequences
- Real-time per-machine output is handled via WebSockets, which is a natural fit for the streaming use case.
- No desktop GUI dependencies; any browser works.
- The server binds to localhost by default, keeping the tool safe without requiring authentication.
- The operator must have a browser available (not a constraint in practice).
- Deployment is `python -m classctl` or similar — no "install a desktop app" step.
- CLI and web share the same core; the web server is one of two presentation layers, not the whole application.
