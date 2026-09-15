"""In-memory WebSocket hub: who is connected to which game."""
from __future__ import annotations

import asyncio


class Hub:
    def __init__(self):
        self._games: dict[str, dict[str, object]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, gid: str) -> asyncio.Lock:
        return self._locks.setdefault(gid, asyncio.Lock())

    def join(self, gid: str, player: str, ws):
        self._games.setdefault(gid, {})[player] = ws

    def leave(self, gid: str, player: str, ws):
        conns = self._games.get(gid)
        if conns is not None and conns.get(player) is ws:
            del conns[player]
            if not conns:
                self._games.pop(gid, None)

    def online(self, gid: str) -> list:
        return list(self._games.get(gid, {}).keys())

    def player_online(self, player: str) -> bool:
        return any(player in conns for conns in self._games.values())

    async def broadcast(self, gid: str, message: dict, exclude: str | None = None):
        conns = list(self._games.get(gid, {}).items())
        if not conns:
            return
        async with self._lock(gid):
            for p, ws in conns:
                if p == exclude:
                    continue
                try:
                    await ws.send_json(message)
                except Exception:
                    pass
