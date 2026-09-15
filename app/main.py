"""FastAPI app: HTTP API + WebSocket realtime for the two-player Sudoku app."""
from __future__ import annotations

import logging
import os
import secrets
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


def create_app(db_path=None, secret=None, passcode=None, static_dir=None) -> FastAPI:
    base = Path(__file__).resolve().parent.parent
    db_path = db_path or os.environ.get("SUDOKU_DB", str(base / "data" / "sudoku.db"))
    secret = secret or os.environ.get("AUTH_SECRET") or secrets.token_hex(16)
    passcode = passcode or os.environ.get("PASSCODE", "0000")
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
        player = authmod.verify_token(secret, tok)
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

    @app.post("/api/auth")
    def do_auth(body: AuthBody, request: Request):
        ip = request.client.host if request.client else "?"
        if not limiter.allow(ip):
            raise HTTPException(status_code=429, detail="too many attempts, try later")
        if not authmod.consteq(body.passcode, passcode):
            raise HTTPException(status_code=401, detail="wrong passcode")
        if body.player not in authmod.PLAYERS:
            raise HTTPException(status_code=400, detail="pick One or Two")
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
        partner = state.other(player)
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
        if player not in authmod.PLAYERS or authmod.verify_token(secret, token) != player:
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
        with closing(db()) as conn:
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
                if not isinstance(msg, dict):
                    continue
                mtype = msg.get("type")
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
