"""FastAPI app: HTTP API + WebSocket realtime for the two-player Sudoku app."""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from contextlib import closing
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth as authmod
from . import engine, state
from .realtime import Hub

log = logging.getLogger("sudoku")


class AuthBody(BaseModel):
    passcode: str
    player: str


class NewBody(BaseModel):
    kind: str
    difficulty: str


def create_app(db_path=None, secret=None, passcode=None, static_dir=None, players=None) -> FastAPI:
    base = Path(__file__).resolve().parent.parent
    db_path = db_path or os.environ.get("SUDOKU_DB", str(base / "data" / "sudoku.db"))
    secret = secret or os.environ.get("AUTH_SECRET") or secrets.token_hex(16)
    passcode = passcode or os.environ.get("PASSCODE", "0000")
    if players is None:
        players = os.environ.get("SUDOKU_PLAYERS", "one,two")
    if isinstance(players, str):
        players = tuple(p.strip() for p in players.split(",") if p.strip())
    if len(players) != 2:
        raise ValueError("SUDOKU_PLAYERS must be exactly two comma-separated names")
    static_dir = os.path.abspath(static_dir or os.environ.get("SUDOKU_STATIC", str(base / "static")))
    os.makedirs(static_dir, exist_ok=True)
    state.init_db(db_path)

    hub = Hub()
    limiter = authmod.RateLimiter(8, 300)

    app = FastAPI(title="Our Sudoku", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(GZipMiddleware, minimum_size=500)
    app.state.db_path = db_path  # exposed for integration tests

    def db():
        return state.connect(db_path)

    def current_player(request: Request, token: str = Query("")) -> str:
        tok = token or request.headers.get("authorization", "").removeprefix("Bearer ")
        player = authmod.verify_token(secret, tok, players)
        if not player:
            raise HTTPException(status_code=401, detail="invalid token")
        return player

    class AuthBody(BaseModel):
        passcode: str
        player: str

    class NewBody(BaseModel):
        kind: str
        difficulty: str

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/who")
    def who():
        return {"players": list(players)}

    @app.post("/api/auth")
    def do_auth(body: AuthBody, request: Request):
        ip = request.client.host if request.client else "?"
        if not authmod.consteq(body.passcode, passcode):
            # only failed attempts count toward the limit
            if not limiter.allow(ip):
                raise HTTPException(status_code=429, detail="too many attempts, try later")
            raise HTTPException(status_code=401, detail="wrong passcode")
        limiter.reset(ip)
        if body.player not in players:
            raise HTTPException(status_code=400, detail="unknown player")
        return {"ok": True, "player": body.player, "token": authmod.make_token(secret, body.player)}

    @app.post("/api/games")
    def new_game(body: NewBody, player: str = Depends(current_player)):
        if body.kind not in ("coop", "solo"):
            raise HTTPException(status_code=400, detail="kind must be coop or solo")
        if body.difficulty not in engine.DIFFICULTIES:
            raise HTTPException(status_code=400, detail="unknown difficulty")
        with closing(db()) as conn:
            g = state.create_game(conn, body.kind, body.difficulty, player)
        return {"game": state.public_game(g)}

    def card(g: dict) -> dict:
        return state.public_game(g)

    @app.get("/api/home")
    def home(player: str = Depends(current_player)):
        with closing(db()) as conn:
            games = state.list_games(conn)
        partner = state.other(player, players)
        active_coop = [g for g in games if g["kind"] == "coop" and g["state"] == "active"]
        joinable = [g for g in games if g["kind"] == "coop" and g["state"] == "waiting" and g["creator"] != player]
        my_open = [g for g in games if g["kind"] == "coop" and g["state"] == "waiting" and g["creator"] == player]
        solo_active = [g for g in games if g["kind"] == "solo" and g["state"] == "active" and player in g["players"]]
        recent = [g for g in games if g["state"] == "completed" and (g["kind"] == "coop" or player in g["players"])][:12]
        return {
            "you": player,
            "partner": partner,
            "partner_online": hub.player_online(partner),
            "continue": card(active_coop[0]) if active_coop else None,
            "also_active": [card(g) for g in active_coop[1:4]],
            "joinable": [card(g) for g in joinable],
            "my_open": [card(g) for g in my_open],
            "solo_games": [card(g) for g in solo_active],
            "solo": card(solo_active[0]) if solo_active else None,
            "recent": [card(g) for g in recent],
        }

    @app.get("/api/games/{gid}")
    def get_game(gid: str, player: str = Depends(current_player)):
        with closing(db()) as conn:
            g = state.get_game(conn, gid)
        if g is None:
            raise HTTPException(status_code=404, detail="no such game")
        if g["kind"] == "solo" and player not in g["players"]:
            raise HTTPException(status_code=403, detail="that solo game isn't yours")
        return {"game": state.public_game(g)}

    @app.delete("/api/games/{gid}")
    async def delete_game(gid: str, player: str = Depends(current_player)):
        with closing(db()) as conn:
            g = state.get_game(conn, gid)
            if g is None:
                raise HTTPException(status_code=404, detail="no such game")
            if player not in g["players"]:
                raise HTTPException(status_code=403, detail="not your game")
            conn.execute("DELETE FROM games WHERE id=?", (gid,))
            conn.commit()
        # kick everyone still in the game; clients treat 4404 as "game gone"
        await hub.close_all(gid, 4404)
        return {"ok": True}

    @app.post("/api/games/{gid}/join")
    def join_game(gid: str, player: str = Depends(current_player)):
        with closing(db()) as conn:
            g = state.get_game(conn, gid)
            if g is None:
                raise HTTPException(status_code=404, detail="no such game")
            if g["kind"] == "solo" and player not in g["players"]:
                raise HTTPException(status_code=403, detail="that solo game isn't yours")
            if g["state"] != "completed":
                g = state.join(g, player)
                state.save_game(conn, g)
        return {"game": state.public_game(g)}

    @app.websocket("/ws/games/{gid}")
    async def game_ws(ws: WebSocket, gid: str, player: str = Query(...), token: str = Query("")):
        if player not in players or authmod.verify_token(secret, token, players) != player:
            await ws.close(code=4401)
            return
        with closing(db()) as conn:
            g = state.get_game(conn, gid)
        if g is None:
            await ws.close(code=4404)
            return
        if g["kind"] == "solo" and player not in g["players"]:
            await ws.close(code=4403)
            return

        await ws.accept()
        hub.join(gid, player, ws)
        last_seen = time.time()

        async def watchdog(ws=ws, gid=gid, player=player):
            # server-side reap: half-open sockets (iOS backgrounding, dead
            # client processes) never deliver a close frame — the kernel pair
            # can linger for hours. Probe actively: if the client is silent
            # for 60s AND doesn't answer a server ping within 15s, close.
            silent_probe = None
            while True:
                await asyncio.sleep(15)
                idle = time.time() - last_seen
                if idle < 60:
                    continue
                if silent_probe is None:
                    silent_probe = time.time()
                    try:
                        await ws.send_json({"type": "ping"})
                    except Exception:
                        return
                elif time.time() - silent_probe > 15:
                    try:
                        await ws.close(code=4408)
                    except Exception:
                        pass
                    return

        wd = asyncio.create_task(watchdog())
        with closing(db()) as conn:
            # a co-op player opening the board counts as joining the game
            if g["kind"] == "coop" and g["state"] != "completed":
                prev_state = g["state"]
                g = state.join(g, player)
                state.save_game(conn, g)
                if g["state"] != prev_state:
                    # partner's join woke the game — tell whoever is already here
                    await hub.broadcast(gid, {"type": "state", "game": state.public_game(g)}, exclude=player)
            g = state.get_game(conn, gid)
            if g is None:
                hub.leave(gid, player, ws)
                await ws.close(code=4404)
                return
            if g["state"] == "active" and g["running_since"] is None:
                state.resume_timer(g)
                state.save_game(conn, g)
        try:
            await ws.send_json({"type": "state", "game": state.public_game(g)})
            await hub.broadcast(gid, {"type": "presence", "online": hub.online(gid)}, exclude=player)
            while True:
                msg = await ws.receive_json()
                last_seen = time.time()
                if not isinstance(msg, dict):
                    continue
                mtype = msg.get("type")
                if mtype in ("ping", "pong"):
                    if mtype == "ping":
                        await ws.send_json({"type": "pong"})
                    continue
                with closing(db()) as conn:
                    g = state.get_game(conn, gid)
                    if g is None:
                        break
                    err = state.apply_op(g, player, msg)
                    if err:
                        await ws.send_json({"type": "error", "error": err})
                        continue
                    state.save_game(conn, g)
                await hub.broadcast(gid, {"type": "state", "game": state.public_game(g)})
        except WebSocketDisconnect:
            pass
        except Exception:
            log.exception("ws handler error")
        finally:
            wd.cancel()
            hub.leave(gid, player, ws)
            try:
                with closing(db()) as conn:
                    g = state.get_game(conn, gid)
                    if g is not None and not hub.online(gid):
                        state.pause_timer(g)
                        state.save_game(conn, g)
            except Exception:
                log.exception("ws cleanup error")
            await hub.broadcast(gid, {"type": "presence", "online": hub.online(gid)})

    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app


app = create_app()
