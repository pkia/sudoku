"""Full two-client WebSocket co-op lifecycle, per the spec's test script."""
import time

import pytest
from fastapi.testclient import TestClient

from app import state as st
from app.main import create_app

PASSCODE = "2468"


@pytest.fixture()
def client(tmp_path):
    db = str(tmp_path / "ws.db")
    app = create_app(
        db_path=db, secret="test-secret", passcode=PASSCODE, static_dir=str(tmp_path / "static")
    )
    with TestClient(app) as c:
        yield c


def tok(client, player):
    r = client.post("/api/auth", json={"passcode": PASSCODE, "player": player})
    return r.json()["token"]


def recv_until(ws, mtype, timeout_s=5):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        msg = ws.receive_json()
        if msg.get("type") == mtype:
            return msg
    raise TimeoutError(f"no {mtype} message")


def ws_connect(client, gid, player, token):
    return client.websocket_connect(f"/ws/games/{gid}?player={player}&token={token}")


def sync_both(a, b):
    """After any op both sockets receive one state message; drain symmetrically."""
    ga = recv_until(a, "state")["game"]
    gb = recv_until(b, "state")["game"]
    return ga, gb


def test_coop_full_lifecycle(client):
    one, two = tok(client, "one"), tok(client, "two")

    # One creates a hard game
    g = client.post("/api/games?token=" + one, json={"kind": "coop", "difficulty": "hard"}).json()["game"]
    gid = g["id"]

    # Two joins from her home list
    g = client.post(f"/api/games/{gid}/join?token=" + two).json()["game"]
    assert g["state"] == "active"

    # Both connect
    with ws_connect(client, gid, "one", one) as we, ws_connect(client, gid, "two", two) as ws:
        se = recv_until(we, "state")["game"]
        ss = recv_until(ws, "state")["game"]
        assert se["state"] == ss["state"] == "active"

        # One receives presence that Two is online
        pres = recv_until(we, "presence")
        assert "two" in pres["online"]

        # find first empty cell
        idx = next(i for i, ch in enumerate(se["puzzle"]) if ch == "0")

        # One enters a correct value -> Two sees it immediately
        correct = int(se_solution(client, gid, one, idx))
        we.send_json({"type": "set", "idx": idx, "value": correct})
        se, ss = sync_both(we, ws)
        assert se["cells"][str(idx)]["v"] == correct
        assert ss["cells"][str(idx)]["v"] == correct
        assert ss["cells"][str(idx)]["by"] == "one"

        # Two enters a wrong value -> both see it flagged, mistake counted
        idx2 = next(i for i, ch in enumerate(se["puzzle"]) if ch == "0" and i != idx)
        wrong = (int(se_solution(client, gid, one, idx2)) % 9) + 1
        if wrong == int(se_solution(client, gid, one, idx2)):
            wrong = wrong % 9 + 1
        ws.send_json({"type": "set", "idx": idx2, "value": wrong})
        ss, se = sync_both(ws, we)
        assert se["cells"][str(idx2)]["wrong"] is True
        assert se["mistakes"]["two"] == 1
        # erase it again
        ws.send_json({"type": "erase", "idx": idx2})
        ss, se = sync_both(ws, we)
        assert str(idx2) not in ss["cells"]

        # Two toggles a candidate note -> One sees it
        ws.send_json({"type": "note", "idx": idx2, "digit": 4})
        ss, se = sync_both(ws, we)
        assert 4 in se["notes"][str(idx2)]

        # One sets a value adjacent -> peer note auto-cleaned (then erase it again:
        # a leftover wrong value would legitimately block completion)
        peer_targets = [p for p in peers(idx2) if se["puzzle"][p] == "0" and str(p) not in se["cells"]]
        if peer_targets:
            p = peer_targets[0]
            we.send_json({"type": "set", "idx": p, "value": 4})
            se, ss = sync_both(we, ws)
            assert 4 not in se["notes"].get(str(idx2), [])
            we.send_json({"type": "erase", "idx": p})
            se, ss = sync_both(we, ws)
            assert str(p) not in se["cells"]

    # Two disconnects; One continues (still receives state after his own moves)
    with ws_connect(client, gid, "one", one) as we:
        recv_until(we, "state")  # consume initial state before sending ops
        # One is connected -> Two's home shows him online even though she left
        assert client.get("/api/home?token=" + two).json()["partner_online"] is True
        idx3 = next(i for i, ch in enumerate(se["puzzle"]) if ch == "0" and str(i) not in se["cells"])
        v3 = int(se_solution(client, gid, one, idx3))
        we.send_json({"type": "set", "idx": idx3, "value": v3})
        se = recv_until(we, "state")["game"]
        assert se["cells"][str(idx3)]["v"] == v3

    # nobody connected now -> partner shows offline
    deadline = time.time() + 5
    while time.time() < deadline:
        if client.get("/api/home?token=" + two).json()["partner_online"] is False:
            break
        time.sleep(0.05)
    assert client.get("/api/home?token=" + two).json()["partner_online"] is False

    # Two returns -> syncs to authoritative state
    with ws_connect(client, gid, "two", two) as ws:
        ss = recv_until(ws, "state")["game"]
        assert ss["cells"][str(idx3)]["v"] == v3
        assert ss["cells"][str(idx)]["v"] == correct

    # Finish the puzzle together -> both see completion
    with ws_connect(client, gid, "one", one) as we, ws_connect(client, gid, "two", two) as ws:
        se, ss = sync_both(we, ws)
        cur = se
        sol = sol_of(client, gid, one)
        for i, ch in enumerate(cur["puzzle"]):
            if ch == "0" and str(i) not in cur["cells"]:
                we.send_json({"type": "set", "idx": i, "value": int(sol[i])})
                se, ss = sync_both(we, ws)
                if se["state"] == "completed":
                    break
        assert se["state"] == "completed"
        assert ss["state"] == "completed"
        assert ss["running"] is False

    # Home shows it in recent, solved together
    home = client.get("/api/home?token=" + one).json()
    assert home["recent"][0]["id"] == gid
    assert home["recent"][0]["state"] == "completed"


def se_solution(client, gid, token, idx):
    """Read the solution char for idx straight from the test DB (server-side truth)."""
    return sol_of(client, gid, token)[idx]


def sol_of(client, gid, token):
    # reach into the app's DB through a debug-ish path: re-derive via API is not
    # possible (solution is never sent to clients) -> use the state module directly
    app = client.app
    # create_app closure stored db path on module attr for tests
    import sqlite3

    db_path = app.state.db_path
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT solution FROM games WHERE id=?", (gid,)).fetchone()
    conn.close()
    return row[0]


def peers(idx):
    from app.engine import PEERS

    return PEERS[idx]


def test_timer_pauses_when_last_socket_leaves(client):
    one = tok(client, "one")
    g = client.post("/api/games?token=" + one, json={"kind": "solo", "difficulty": "easy"}).json()["game"]
    gid = g["id"]

    with ws_connect(client, gid, "one", one) as we:
        s = recv_until(we, "state")["game"]
        assert s["running"] is True
        time.sleep(0.3)
    # wait for the server's last-socket disconnect cleanup (timer pause)
    deadline = time.time() + 5
    while time.time() < deadline:
        g = client.get(f"/api/games/{gid}?token=" + one).json()["game"]
        if g["running"] is False:
            break
        time.sleep(0.05)
    assert g["running"] is False
    assert g["elapsed_ms"] >= 250  # ~0.3s accumulated while connected

    # reconnect resumes from accumulated time
    with ws_connect(client, gid, "one", one) as we:
        s = recv_until(we, "state")["game"]
        assert s["running"] is True
        assert s["elapsed_ms"] >= g["elapsed_ms"]


def test_ws_rejects_bad_token(client):
    one = tok(client, "one")
    g = client.post("/api/games?token=" + one, json={"kind": "solo", "difficulty": "easy"}).json()["game"]
    with pytest.raises(Exception):
        with client.websocket_connect(f"/ws/games/{g['id']}?player=one&token=bogus"):
            pass
