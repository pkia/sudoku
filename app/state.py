"""SQLite persistence + pure game operations. One row per game (coop or solo)."""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import time
from contextlib import closing

from . import engine

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  difficulty TEXT NOT NULL,
  puzzle TEXT NOT NULL,
  solution TEXT NOT NULL,
  state TEXT NOT NULL,
  creator TEXT NOT NULL,
  players TEXT NOT NULL,
  cells TEXT NOT NULL,
  notes TEXT NOT NULL,
  mistakes TEXT NOT NULL,
  elapsed_ms REAL NOT NULL DEFAULT 0,
  running_since REAL,
  created_at REAL NOT NULL,
  last_activity REAL NOT NULL,
  completed_at REAL,
  completed_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_games_state ON games(state, last_activity);
"""

_UPDATE = """UPDATE games SET state=:state, players=:players, cells=:cells, notes=:notes,
  mistakes=:mistakes, elapsed_ms=:elapsed_ms, running_since=:running_since,
  last_activity=:last_activity, completed_at=:completed_at, completed_by=:completed_by
  WHERE id=:id"""


def connect(db_path: str):
    d = os.path.dirname(db_path)
    if d:
        os.makedirs(d, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def init_db(db_path: str):
    with closing(connect(db_path)) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def row_to_game(r) -> dict:
    return {
        "id": r["id"],
        "kind": r["kind"],
        "difficulty": r["difficulty"],
        "puzzle": r["puzzle"],
        "solution": r["solution"],
        "state": r["state"],
        "creator": r["creator"],
        "players": json.loads(r["players"]),
        "cells": json.loads(r["cells"]),
        "notes": json.loads(r["notes"]),
        "mistakes": json.loads(r["mistakes"]),
        "elapsed_ms": r["elapsed_ms"] or 0.0,
        "running_since": r["running_since"],
        "created_at": r["created_at"],
        "last_activity": r["last_activity"],
        "completed_at": r["completed_at"],
        "completed_by": r["completed_by"],
    }


def create_game(conn, kind: str, difficulty: str, creator: str) -> dict:
    p = engine.generate(difficulty)
    now = time.time()
    g = {
        "id": secrets.token_urlsafe(6),
        "kind": kind,
        "difficulty": difficulty,
        "puzzle": p.puzzle,
        "solution": p.solution,
        "state": "active" if kind == "solo" else "waiting",
        "creator": creator,
        "players": [creator],
        "cells": {},
        "notes": {},
        "mistakes": {},
        "elapsed_ms": 0.0,
        "running_since": now if kind == "solo" else None,
        "created_at": now,
        "last_activity": now,
        "completed_at": None,
        "completed_by": None,
    }
    conn.execute(
        """INSERT INTO games (id, kind, difficulty, puzzle, solution, state, creator, players,
           cells, notes, mistakes, elapsed_ms, running_since, created_at, last_activity,
           completed_at, completed_by) VALUES (:id, :kind, :difficulty, :puzzle, :solution,
           :state, :creator, :players, :cells, :notes, :mistakes, :elapsed_ms, :running_since,
           :created_at, :last_activity, :completed_at, :completed_by)""",
        {**g, "players": json.dumps(g["players"]), "cells": json.dumps(g["cells"]),
         "notes": json.dumps(g["notes"]), "mistakes": json.dumps(g["mistakes"])},
    )
    conn.commit()
    return g


def get_game(conn, gid: str):
    r = conn.execute("SELECT * FROM games WHERE id=?", (gid,)).fetchone()
    return row_to_game(r) if r else None


def save_game(conn, g: dict):
    conn.execute(
        _UPDATE,
        {
            "id": g["id"], "state": g["state"],
            "players": json.dumps(g["players"]), "cells": json.dumps(g["cells"]),
            "notes": json.dumps(g["notes"]), "mistakes": json.dumps(g["mistakes"]),
            "elapsed_ms": g["elapsed_ms"], "running_since": g["running_since"],
            "last_activity": g["last_activity"], "completed_at": g["completed_at"],
            "completed_by": g["completed_by"],
        },
    )
    conn.commit()


def list_games(conn, limit: int = 200) -> list:
    rows = conn.execute(
        "SELECT * FROM games ORDER BY last_activity DESC LIMIT ?", (limit,)
    ).fetchall()
    return [row_to_game(r) for r in rows]


def other(player: str) -> str:
    return "two" if player == "one" else "one"


# ---------- timer ----------

def live_elapsed_ms(g: dict, now=None) -> float:
    now = time.time() if now is None else now
    base = g["elapsed_ms"] or 0.0
    if g["running_since"] is not None and g["state"] != "completed":
        base += (now - g["running_since"]) * 1000.0
    return base


def pause_timer(g: dict, now=None) -> dict:
    if g["running_since"] is not None and g["state"] == "active":
        g["elapsed_ms"] = live_elapsed_ms(g, now)
        g["running_since"] = None
    return g


def resume_timer(g: dict, now=None) -> dict:
    if g["state"] == "active" and g["running_since"] is None:
        g["running_since"] = time.time() if now is None else now
    return g


# ---------- derived views ----------

def progress_pct(g: dict) -> int:
    need = sum(1 for ch in g["puzzle"] if ch == "0")
    if not need:
        return 100
    sol = g["solution"]
    done = 0
    for k, c in g["cells"].items():
        if str(c.get("v")) == sol[int(k)]:
            done += 1
    return int(round(100 * done / need))


def public_game(g: dict, now=None) -> dict:
    """Client view: no solution string, live timer."""
    now = time.time() if now is None else now
    return {
        "id": g["id"],
        "kind": g["kind"],
        "difficulty": g["difficulty"],
        "state": g["state"],
        "creator": g["creator"],
        "players": g["players"],
        "puzzle": g["puzzle"],
        "cells": g["cells"],
        "notes": g["notes"],
        "mistakes": g["mistakes"],
        "elapsed_ms": int(live_elapsed_ms(g, now)),
        "running": g["running_since"] is not None and g["state"] != "completed",
        "created_at": g["created_at"],
        "last_activity": g["last_activity"],
        "completed_at": g["completed_at"],
        "completed_by": g["completed_by"],
        "progress": progress_pct(g),
    }


# ---------- pure game operations ----------

def _check_complete(g: dict, player: str, now: float):
    if g["state"] == "completed":
        return
    sol = g["solution"]
    for i in range(81):
        if g["puzzle"][i] != "0":
            continue
        c = g["cells"].get(str(i))
        if not c or str(c.get("v")) != sol[i]:
            return
    g["state"] = "completed"
    g["elapsed_ms"] = live_elapsed_ms(g, now)
    g["running_since"] = None
    g["completed_at"] = now
    g["completed_by"] = player


def apply_op(g: dict, player: str, op: dict):
    """Apply a client op to the game dict in place. Returns error string or None."""
    t = op.get("type")
    if g["state"] == "completed":
        return "game is finished"
    now = time.time()

    if t == "start":
        if g["state"] == "waiting":
            g["state"] = "active"
            g["running_since"] = now
            g["last_activity"] = now
        return None

    idx = op.get("idx")
    if not isinstance(idx, int) or not (0 <= idx <= 80) or isinstance(idx, bool):
        return "bad index"
    given = g["puzzle"][idx] != "0"

    if t == "set":
        v = op.get("value")
        if isinstance(v, bool) or not isinstance(v, int) or not (1 <= v <= 9):
            return "bad value"
        if given:
            return "can't change a given cell"
        prev = g["cells"].get(str(idx))
        if prev and prev.get("v") == v:
            g["last_activity"] = now
            return None
        wrong = str(v) != g["solution"][idx]
        g["cells"][str(idx)] = {"v": v, "by": player, "t": now, "wrong": wrong}
        if wrong:
            m = g["mistakes"]
            m[player] = m.get(player, 0) + 1
        g["notes"].pop(str(idx), None)
        for p in engine.PEERS[idx]:
            k = str(p)
            ns = g["notes"].get(k)
            if ns and v in ns:
                ns.remove(v)
                if not ns:
                    g["notes"].pop(k, None)
        g["last_activity"] = now
        _check_complete(g, player, now)
        return None

    if t == "erase":
        if given:
            return "can't erase a given cell"
        if str(idx) in g["cells"]:
            del g["cells"][str(idx)]
            g["last_activity"] = now
        return None

    if t == "note":
        d = op.get("digit")
        if isinstance(d, bool) or not isinstance(d, int) or not (1 <= d <= 9):
            return "bad digit"
        if given:
            return "can't note a given cell"
        if str(idx) in g["cells"]:
            return "cell already has a value"
        ns = g["notes"].setdefault(str(idx), [])
        if d in ns:
            ns.remove(d)
        else:
            ns.append(d)
            ns.sort()
        if not ns:
            g["notes"].pop(str(idx), None)
        g["last_activity"] = now
        return None

    if t == "notes_clear":
        if str(idx) in g["notes"]:
            g["notes"].pop(str(idx))
            g["last_activity"] = now
        return None

    if t == "undo":
        if given:
            return "can't undo a given cell"
        v = op.get("value", 0)
        prev_notes = op.get("notes", [])
        prev_by = op.get("by") or player
        if prev_by not in ("one", "two"):
            prev_by = player
        if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 9:
            wrong = str(v) != g["solution"][idx]
            g["cells"][str(idx)] = {"v": v, "by": prev_by, "t": now, "wrong": wrong}
        else:
            g["cells"].pop(str(idx), None)
        if isinstance(prev_notes, list) and prev_notes:
            cleaned = sorted({d for d in prev_notes if isinstance(d, int) and 1 <= d <= 9})
            if cleaned:
                g["notes"][str(idx)] = cleaned
            else:
                g["notes"].pop(str(idx), None)
        else:
            g["notes"].pop(str(idx), None)
        g["last_activity"] = now
        _check_complete(g, player, now)
        return None

    return "unknown op"


def join(g: dict, player: str) -> dict:
    if player not in g["players"]:
        g["players"].append(player)
    if g["kind"] == "coop" and g["state"] == "waiting":
        g["state"] = "active"
        g["running_since"] = time.time()
    g["last_activity"] = time.time()
    return g
