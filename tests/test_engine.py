import random

import pytest

from app import engine


def assert_no_given_conflicts(grid):
    for i, v in enumerate(grid):
        if v:
            for p in engine.PEERS[i]:
                assert grid[p] != v, f"conflict at {i} with peer {p}"


def test_known_puzzle_solves():
    # Classic example puzzle (has a unique solution).
    rows = [
        "530070000",
        "600195000",
        "098000060",
        "800060003",
        "400803001",
        "700020006",
        "060000280",
        "000419005",
        "000080079",
    ]
    grid = [int(c) for r in rows for c in r]
    sol = engine.solve_one(grid)
    assert sol is not None
    # solution respects givens and has no conflicts
    for i, v in enumerate(grid):
        if v:
            assert sol[i] == v
    assert_no_given_conflicts(sol)
    assert engine.solution_count(grid, 2) == 1


def test_invalid_puzzle_has_zero_solutions():
    grid = [0] * 81
    grid[0] = 5
    grid[1] = 5  # same row conflict
    assert engine.solution_count(grid, 2) == 0
    assert engine.solve_one(grid) is None


@pytest.mark.parametrize("difficulty", engine.DIFFICULTIES)
def test_generate_valid_unique_banded(difficulty):
    rng = random.Random(20260915)
    for _ in range(4):
        p = engine.generate(difficulty, rng=rng)
        grid = [int(c) for c in p.puzzle]
        sol = [int(c) for c in p.solution]

        assert len(p.puzzle) == 81 and len(p.solution) == 81
        # givens are valid (no conflicts)
        assert_no_given_conflicts(grid)
        # exactly one solution
        assert engine.solution_count(grid, 2) == 1
        # solution extends the puzzle
        for i, v in enumerate(grid):
            if v:
                assert sol[i] == v
        assert_no_given_conflicts(sol)
        # difficulty band
        assert engine.band_ok(difficulty, p.tier, p.clues), (
            f"{difficulty}: tier={p.tier} clues={p.clues}"
        )
        # harder bands have fewer clues than easier ones, broadly
        if difficulty == "easy":
            assert p.clues >= 35
        if difficulty == "expert":
            assert p.clues <= 26


def test_difficulty_ordering_sanity():
    """Easy should never need more technique than expert on average."""
    rng = random.Random(7)
    easy_max = max(engine.generate("easy", rng=rng).tier for _ in range(3))
    exp_min = min(engine.generate("expert", rng=rng).tier for _ in range(3))
    assert easy_max <= exp_min
