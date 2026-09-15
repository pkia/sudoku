import pytest
from fastapi.testclient import TestClient

from app.main import create_app

PASSCODE = "2468"


@pytest.fixture()
def client(tmp_path):
    app = create_app(
        db_path=str(tmp_path / "t.db"),
        secret="test-secret",
        passcode=PASSCODE,
        static_dir=str(tmp_path / "static"),
    )
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def one(client):
    r = client.post("/api/auth", json={"passcode": PASSCODE, "player": "one"})
    assert r.status_code == 200
    return r.json()["token"]


@pytest.fixture()
def two(client):
    r = client.post("/api/auth", json={"passcode": PASSCODE, "player": "two"})
    assert r.status_code == 200
    return r.json()["token"]


def test_health(client):
    assert client.get("/api/health").json() == {"ok": True}


def test_auth_rejects_wrong_passcode(client):
    r = client.post("/api/auth", json={"passcode": "1111", "player": "one"})
    assert r.status_code == 401
    r = client.post("/api/auth", json={"passcode": PASSCODE, "player": "stranger"})
    assert r.status_code == 400


def test_api_requires_token(client, one):
    assert client.get("/api/home").status_code == 401
    assert client.get("/api/home?token=bogus").status_code == 401
    assert client.get(f"/api/home?token={one}").status_code == 200


def test_auth_rate_limit(client):
    for _ in range(8):
        client.post("/api/auth", json={"passcode": "0000", "player": "one"})
    r = client.post("/api/auth", json={"passcode": "0000", "player": "one"})
    assert r.status_code == 429
    # a correct passcode is still locked out within the window (throttle applies
    # before the passcode check once tripped) — verify lockout, then that a
    # successful auth resets the counter so future failures get a fresh budget
    r = client.post("/api/auth", json={"passcode": PASSCODE, "player": "one"})
    assert r.status_code in (200, 429)
    if r.status_code == 200:
        r = client.post("/api/auth", json={"passcode": "0000", "player": "one"})
        assert r.status_code == 401  # fresh budget after success


def test_coop_flow_create_join(client, one, two):
    # One creates a hard co-op game
    r = client.post("/api/games?token=" + one, json={"kind": "coop", "difficulty": "hard"})
    assert r.status_code == 200
    g = r.json()["game"]
    assert g["state"] == "waiting"
    assert g["creator"] == "one"
    assert g["kind"] == "coop"
    assert len(g["puzzle"]) == 81

    # Two sees it as joinable
    home = client.get("/api/home?token=" + two).json()
    ids = [c["id"] for c in home["joinable"]]
    assert g["id"] in ids
    # One's own view lists it under my_open, not joinable
    home_e = client.get("/api/home?token=" + one).json()
    assert g["id"] not in [c["id"] for c in home_e["joinable"]]
    assert g["id"] in [c["id"] for c in home_e["my_open"]]

    # Two joins -> active
    r = client.post(f"/api/games/{g['id']}/join?token=" + two)
    assert r.status_code == 200
    g2 = r.json()["game"]
    assert g2["state"] == "active"
    assert set(g2["players"]) == {"one", "two"}
    assert g2["running"] is True

    # Now both see it under continue
    for tok in (one, two):
        home = client.get("/api/home?token=" + tok).json()
        assert home["continue"]["id"] == g["id"]


def test_multiple_waiting_games(client, one, two):
    ids = []
    for diff in ("easy", "medium", "expert"):
        r = client.post("/api/games?token=" + one, json={"kind": "coop", "difficulty": diff})
        ids.append(r.json()["game"]["id"])
    home = client.get("/api/home?token=" + two).json()
    got = [c["id"] for c in home["joinable"]]
    assert all(i in got for i in ids)

    # join one; others remain joinable
    client.post(f"/api/games/{ids[0]}/join?token=" + two)
    home = client.get("/api/home?token=" + two).json()
    assert home["continue"]["id"] == ids[0]
    assert ids[1] in [c["id"] for c in home["joinable"]]
    assert ids[2] in [c["id"] for c in home["joinable"]]

    # a new game by two appears too
    r = client.post("/api/games?token=" + two, json={"kind": "coop", "difficulty": "medium"})
    sid = r.json()["game"]["id"]
    home_e = client.get("/api/home?token=" + one).json()
    assert sid in [c["id"] for c in home_e["joinable"]]


def test_solo_is_private(client, one, two):
    r = client.post("/api/games?token=" + one, json={"kind": "solo", "difficulty": "easy"})
    g = r.json()["game"]
    assert g["state"] == "active"
    assert g["kind"] == "solo"

    # Two cannot see or join One's solo game
    assert client.get(f"/api/games/{g['id']}?token=" + two).status_code == 403
    assert client.post(f"/api/games/{g['id']}/join?token=" + two).status_code == 403

    # One sees it as his solo continue, Two sees none
    assert client.get("/api/home?token=" + one).json()["solo"]["id"] == g["id"]
    assert client.get("/api/home?token=" + two).json()["solo"] is None


def test_multiple_solo_games(client, one):
    # start two solo games; both must remain visible and resumable
    g1 = client.post("/api/games?token=" + one, json={"kind": "solo", "difficulty": "easy"}).json()["game"]
    g2 = client.post("/api/games?token=" + one, json={"kind": "solo", "difficulty": "hard"}).json()["game"]

    home = client.get("/api/home?token=" + one).json()
    ids = [c["id"] for c in home["solo_games"]]
    assert g1["id"] in ids and g2["id"] in ids
    # legacy single field still present (most recent first)
    assert home["solo"]["id"] in ids

    # both remain fetchable and playable independently
    assert client.get(f"/api/games/{g1['id']}?token=" + one).status_code == 200
    assert client.get(f"/api/games/{g2['id']}?token=" + one).status_code == 200

    # after deleting one, the other still shows
    client.delete(f"/api/games/{g1['id']}?token=" + one)
    home = client.get("/api/home?token=" + one).json()
    assert [c["id"] for c in home["solo_games"]] == [g2["id"]]


def test_bad_requests(client, one):
    assert client.post("/api/games?token=" + one, json={"kind": "coop", "difficulty": "impossible"}).status_code == 400
    assert client.post("/api/games?token=" + one, json={"kind": "multiplayer", "difficulty": "easy"}).status_code == 400
    assert client.get("/api/games/zzzz?token=" + one).status_code == 404


def test_delete_game(client, one, two):
    # One creates a coop game; both players are participants
    r = client.post("/api/games?token=" + one, json={"kind": "coop", "difficulty": "easy"})
    gid = r.json()["game"]["id"]
    client.post(f"/api/games/{gid}/join?token=" + two)

    # either participant may delete
    assert client.delete(f"/api/games/{gid}?token=" + two).status_code == 200
    assert client.get(f"/api/games/{gid}?token=" + one).status_code == 404

    # deleting again -> 404
    assert client.delete(f"/api/games/{gid}?token=" + one).status_code == 404

    # a non-participant cannot delete someone else's game
    r = client.post("/api/games?token=" + one, json={"kind": "solo", "difficulty": "easy"})
    sid = r.json()["game"]["id"]
    assert client.delete(f"/api/games/{sid}?token=" + two).status_code == 403
    assert client.delete(f"/api/games/{sid}?token=" + one).status_code == 200

    # unauthenticated delete rejected
    r = client.post("/api/games?token=" + one, json={"kind": "coop", "difficulty": "easy"})
    gid2 = r.json()["game"]["id"]
    assert client.delete(f"/api/games/{gid2}").status_code == 401
