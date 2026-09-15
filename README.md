# Two Player Sudoku

A private, mobile-first co-op Sudoku app for exactly two players: One & Two.

- Real co-op: shared board, live sync of values/notes/mistakes/timer over WebSockets
- Solo mode with saved progress and resume
- Genuine generator: every puzzle valid, unique solution, graded difficulty
- No accounts, no codes, no invites — pick your name once, done

## Stack

- FastAPI + WebSockets + SQLite (WAL), single process, systemd service
- Vanilla-JS mobile-first PWA (installable on iOS via Safari → Add to Home Screen)

## Layout

- `app/engine.py` — generator / solver / difficulty grader
- `app/main.py` — HTTP + WS API
- `app/state.py` — SQLite persistence
- `app/realtime.py` — connection manager, authoritative game ops
- `static/` — frontend (no build step)
- `tests/` — pytest: engine correctness + full two-client WS lifecycle

## Run locally

```
python3 -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/pytest -q
venv/bin/uvicorn app.main:app --port 8790
```

## Production

systemd unit `sudoku.service`, port 8790, DB at `data/sudoku.db`.
Passcode gate (shared 4-digit code) set via `PASSCODE` in `.env`.
