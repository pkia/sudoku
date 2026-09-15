# Our Sudoku

A tiny two-player co-op Sudoku — one shared passcode, no accounts, no invites.
Pick your name once and play: shared boards with live sync of values, notes,
mistakes and the timer over WebSockets, or solo with saved progress and resume.

- Real co-op: two players on one board, every cell placement syncs live
- Solo mode with saved progress and resume
- Genuine generator: every puzzle valid, unique solution, graded difficulty
- Installable mobile-first PWA (iOS: Safari → Add to Home Screen)

## Configuration

Everything is env-driven (a `.env` file works — see `.gitignore`):

| Variable | Default | What |
|---|---|---|
| `PASSCODE` | `0000` | the shared 4-digit code |
| `SUDOKU_PLAYERS` | `one,two` | exactly two comma-separated player names |
| `AUTH_SECRET` | random | token-signing secret (set it or tokens die on restart) |
| `SUDOKU_DB` | `data/sudoku.db` | SQLite path |

## Stack

- FastAPI + WebSockets + SQLite (WAL), single process, systemd service
- Vanilla-JS mobile-first PWA (no build step)

## Layout

- `app/engine.py` — generator / solver / difficulty grader
- `app/main.py` — HTTP + WS API
- `app/state.py` — SQLite persistence + game operations
- `app/realtime.py` — connection manager, authoritative game ops
- `static/` — frontend (no build step)
- `tests/` — pytest: engine correctness + full two-client WS lifecycle

## Run locally

    python3 -m venv venv && venv/bin/pip install -r requirements.txt
    PASSCODE=1234 SUDOKU_PLAYERS=alice,bob venv/bin/uvicorn app.main:app --port 8790

## Tests

    venv/bin/python -m pytest -q
