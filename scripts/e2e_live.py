"""Live end-to-end co-op test against the running server on :8790.

Simulates both players on two phones: create, join, bidirectional sync,
disconnect/reconnect resync, completion. Prints PASS/FAIL per scenario.
"""
import asyncio
import json
import sys
import time

import urllib.request

BASE = "http://127.0.0.1:8790"


def http(method, path, body=None, token=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def read_env():
    vals = {}
    with open("/home/ev/apps/sudoku/.env") as f:
        for line in f:
            if "=" in line:
                k, v = line.strip().split("=", 1)
                vals[k] = v
    return vals


async def recv_until(ws, mtype, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
        if msg.get("type") == mtype:
            return msg
    raise TimeoutError(mtype)

async def main():
    import websockets

    env = read_env()
    ok = fail = 0

    def check(name, cond, extra=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"  PASS  {name}")
        else:
            fail += 1
            print(f"  FAIL  {name} {extra}")

    P1, P2 = [p.strip() for p in env.get("SUDOKU_PLAYERS", "one,two").split(",")]

# auth both players
    s, ev = http("POST", "/api/auth", {"passcode": env["PASSCODE"], "player": P1})
    check("p1 auth", s == 200)
    s, sa = http("POST", "/api/auth", {"passcode": env["PASSCODE"], "player": P2})
    check("p2 auth", s == 200)
    et, st = ev["token"], sa["token"]

    # p1 creates hard coop game
    s, r = http("POST", "/api/games", {"kind": "coop", "difficulty": "hard"}, et)
    check("create hard coop", s == 200)
    gid = r["game"]["id"]

    # p2 sees it joinable
    s, r = http("GET", "/api/home", None, st)
    check("p2 home joinable", any(c["id"] == gid for c in r["joinable"]))
    check("partner online flag false initially", r["partner_online"] is False)

    # p1 connects first (waiting)
    ws_url = f"ws://127.0.0.1:8790/ws/games/{gid}"
    async with websockets.connect(f"{ws_url}?player=" + P1 + "&token={et}") as we:
        first = json.loads(await we.recv())
        check("p1 initial state", first["type"] == "state" and first["game"]["state"] == "waiting")

        # p2 connects -> auto-join -> active; p1 gets state + presence
        async with websockets.connect(f"{ws_url}?player=" + P2 + "&token={st}") as wsa:
            sar = json.loads(await wsa.recv())
            check("p2 initial state active", sar["game"]["state"] == "active")
            ev_state = json.loads(await we.recv())
            check("p1 sees active after p2 joins", ev_state["game"]["state"] == "active")
            pres = json.loads(await we.recv())
            check("p1 presence shows p2", P2 in pres["online"])

            # p1 sets a value
            puzzle = sar["game"]["puzzle"]
            idx = next(i for i, ch in enumerate(puzzle) if ch == "0")
            await we.send(json.dumps({"type": "set", "idx": idx, "value": 5}))
            a1 = await recv_until(we, "state")
            a2 = await recv_until(wsa, "state")
            check("p1 set -> p1 state", a1["game"]["cells"].get(str(idx), {}).get("v") == 5)
            check("p1 set -> p2 sees it", a2["game"]["cells"][str(idx)]["v"] == 5)
            check("by field", a2["game"]["cells"][str(idx)]["by"] == P1)

            # p2 sets a different value
            idx2 = next(i for i, ch in enumerate(puzzle) if ch == "0" and i != idx)
            await wsa.send(json.dumps({"type": "set", "idx": idx2, "value": 7}))
            b1 = await recv_until(wsa, "state")
            b2 = await recv_until(we, "state")
            check("p2 set -> p1 sees it", b2["game"]["cells"][str(idx2)]["v"] == 7)
            check("by field p2", b2["game"]["cells"][str(idx2)]["by"] == P2)

            # p2 drops; p1 continues
        # p2's disconnect triggers a presence broadcast; p1's own next op
        # triggers a state broadcast. order is racy — collect until both seen.
        idx3 = next(i for i, ch in enumerate(puzzle) if ch == "0" and i not in (idx, idx2))
        await we.send(json.dumps({"type": "set", "idx": idx3, "value": 3}))
        saw_presence = None
        deadline = time.time() + 4
        last_state = None
        while time.time() < deadline and (last_state is None or saw_presence is None):
            msg = json.loads(await asyncio.wait_for(we.recv(), timeout=4))
            if msg["type"] == "state":
                last_state = msg["game"]
            elif msg["type"] == "presence":
                saw_presence = msg["online"]
        check("p1 continues alone", last_state and last_state["cells"].get(str(idx3), {}).get("v") == 3)
        check("presence after p2 leaves", saw_presence is not None and P2 not in saw_presence, f"(got {saw_presence})")

    # p2 reconnects -> authoritative sync
    async with websockets.connect(f"{ws_url}?player=" + P2 + "&token={st}") as wsa:
        sar = json.loads(await wsa.recv())
        check("p2 resync has p1's moves", sar["game"]["cells"].get(str(idx3), {}).get("v") == 3)
        check("p2 resync state active", sar["game"]["state"] == "active")

    # complete the game: hint every non-given cell (hint overwrites wrong values too)
    async with websockets.connect(f"{ws_url}?player=" + P1 + "&token={et}") as we:
        state = json.loads(await asyncio.wait_for(we.recv(), timeout=5))["game"]
        for i, ch in enumerate(state["puzzle"]):
            if ch != "0":
                continue
            await we.send(json.dumps({"type": "hint", "idx": i}))
            resp = await recv_until(we, "state")
            state = resp["game"]
            if state["state"] == "completed":
                break
        last = state
        check("completed via hints", last["state"] == "completed")
        check("timer stopped", last["running"] is False)

    # home shows recent
    s, r = http("GET", "/api/home", None, st)
    check("recent contains solved game", any(c["id"] == gid and c["state"] == "completed" for c in r["recent"]))

    # wrong passcode rejected
    s, _ = http("POST", "/api/auth", {"passcode": "9999", "player": P1})
    check("wrong passcode rejected", s == 401)

    # unauthenticated access rejected
    s, _ = http("GET", "/api/home")
    check("no-token home rejected", s == 401)

    print(f"\n{ok} passed, {fail} failed")
    sys.exit(1 if fail else 0)


asyncio.run(main())
