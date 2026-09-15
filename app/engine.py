"""Sudoku engine: generation, solving, uniqueness, difficulty rating.

Pure Python, no deps. Grid = list of 81 ints, 0 = empty; index = row*9 + col.
Difficulty is graded by which tier of human techniques solves the puzzle:
  1 = naked singles only
  2 = + hidden singles
  3 = + locked candidates / naked pairs
  4 = needs more (backtracking)
"""
from __future__ import annotations

import random
from dataclasses import dataclass

FULL = 0b1111111110  # bits 1..9


def _precompute():
    idx = []
    for i in range(81):
        r, c = divmod(i, 9)
        b = (r // 3) * 3 + (c // 3)
        idx.append((r, c, b))
    peers = []
    for i in range(81):
        r, c, _ = idx[i]
        s = set()
        for j in range(9):
            s.add(r * 9 + j)
            s.add(j * 9 + c)
        br, bc = (r // 3) * 3, (c // 3) * 3
        for rr in range(br, br + 3):
            for cc in range(bc, bc + 3):
                s.add(rr * 9 + cc)
        s.discard(i)
        peers.append(frozenset(s))
    units = []
    for r in range(9):
        units.append(tuple(r * 9 + c for c in range(9)))
    for c in range(9):
        units.append(tuple(r * 9 + c for r in range(9)))
    for br in range(0, 9, 3):
        for bc in range(0, 9, 3):
            units.append(tuple((br + r) * 9 + (bc + c) for r in range(3) for c in range(3)))
    return idx, peers, units


IDX, PEERS, UNITS = _precompute()

DIFFICULTIES = ("easy", "medium", "hard", "expert")
# difficulty -> (dig target clues, (acceptable clue window), required tier)
BANDS = {
    "easy": (38, (35, 46), 1),
    "medium": (32, (30, 35), 2),
    "hard": (28, (26, 31), 3),
    "expert": (23, (21, 26), 4),
}


def solution_count(grid, limit=2):
    """Count solutions up to `limit`. Returns 0/1/2 quickly for uniqueness."""
    rows = [0] * 9
    cols = [0] * 9
    boxes = [0] * 9
    for i, v in enumerate(grid):
        if v:
            r, c, b = IDX[i]
            bit = 1 << v
            if (rows[r] | cols[c] | boxes[b]) & bit:
                return 0
            rows[r] |= bit
            cols[c] |= bit
            boxes[b] |= bit
    todo = {i for i, v in enumerate(grid) if not v}
    count = 0

    def dfs():
        nonlocal count
        if not todo:
            count += 1
            return count >= limit
        best = -1
        best_mask = 0
        best_n = 10
        for i in todo:
            r, c, b = IDX[i]
            mask = FULL & ~(rows[r] | cols[c] | boxes[b])
            n = mask.bit_count()
            if n < best_n:
                best, best_mask, best_n = i, mask, n
                if n <= 1:
                    break
        if best_n == 0:
            return False
        todo.discard(best)
        r, c, b = IDX[best]
        m = best_mask
        stop = False
        while m:
            bit = m & -m
            m ^= bit
            rows[r] |= bit
            cols[c] |= bit
            boxes[b] |= bit
            stop = dfs()
            rows[r] ^= bit
            cols[c] ^= bit
            boxes[b] ^= bit
            if stop:
                break
        todo.add(best)
        return stop

    dfs()
    return count


def solve_one(grid):
    """Return a solution as list of 81 ints, or None."""
    g = list(grid)
    rows = [0] * 9
    cols = [0] * 9
    boxes = [0] * 9
    for i, v in enumerate(g):
        if v:
            r, c, b = IDX[i]
            bit = 1 << v
            if (rows[r] | cols[c] | boxes[b]) & bit:
                return None
            rows[r] |= bit
            cols[c] |= bit
            boxes[b] |= bit
    todo = {i for i, v in enumerate(g) if not v}

    def dfs():
        if not todo:
            return True
        best = -1
        best_mask = 0
        best_n = 10
        for i in todo:
            r, c, b = IDX[i]
            mask = FULL & ~(rows[r] | cols[c] | boxes[b])
            n = mask.bit_count()
            if n < best_n:
                best, best_mask, best_n = i, mask, n
                if n <= 1:
                    break
        if best_n == 0:
            return False
        todo.discard(best)
        r, c, b = IDX[best]
        m = best_mask
        stop = False
        while m:
            bit = m & -m
            m ^= bit
            v = bit.bit_length() - 1
            g[best] = v
            rows[r] |= bit
            cols[c] |= bit
            boxes[b] |= bit
            stop = dfs()
            if stop:
                break
            rows[r] ^= bit
            cols[c] ^= bit
            boxes[b] ^= bit
            g[best] = 0
        todo.add(best)
        return stop

    if dfs():
        return g
    return None


def _random_solution(rng):
    grid = [0] * 81
    rows = [0] * 9
    cols = [0] * 9
    boxes = [0] * 9

    def fill(i):
        if i == 81:
            return True
        r, c, b = IDX[i]
        used = rows[r] | cols[c] | boxes[b]
        cands = [d for d in range(1, 10) if not used & (1 << d)]
        rng.shuffle(cands)
        for d in cands:
            bit = 1 << d
            rows[r] |= bit
            cols[c] |= bit
            boxes[b] |= bit
            grid[i] = d
            if fill(i + 1):
                return True
            rows[r] ^= bit
            cols[c] ^= bit
            boxes[b] ^= bit
            grid[i] = 0
        return False

    fill(0)
    return grid


def _locked_candidates(cand, g):
    """Pointing & claiming eliminations. Returns True if anything changed."""
    changed = False
    # pointing: within a box, digit confined to one row/col -> eliminate elsewhere in that row/col
    for b in range(9):
        cells = UNITS[18 + b]
        cellset = set(cells)
        for d in range(1, 10):
            bit = 1 << d
            spots = [i for i in cells if g[i] == 0 and cand[i] & bit]
            if len(spots) < 2:
                continue
            rs = {IDX[i][0] for i in spots}
            cs = {IDX[i][1] for i in spots}
            if len(rs) == 1:
                r = rs.pop()
                for i in range(r * 9, r * 9 + 9):
                    if g[i] == 0 and i not in cellset and cand[i] & bit:
                        cand[i] &= ~bit
                        changed = True
            if len(cs) == 1:
                c = cs.pop()
                for i in range(c, 81, 9):
                    if g[i] == 0 and i not in cellset and cand[i] & bit:
                        cand[i] &= ~bit
                        changed = True
    # claiming: within a row/col, digit confined to one box -> eliminate elsewhere in box
    for u in range(18):
        unit = UNITS[u]
        unitset = set(unit)
        for d in range(1, 10):
            bit = 1 << d
            spots = [i for i in unit if g[i] == 0 and cand[i] & bit]
            if len(spots) < 2:
                continue
            bs = {IDX[i][2] for i in spots}
            if len(bs) == 1:
                for i in UNITS[18 + bs.pop()]:
                    if g[i] == 0 and i not in unitset and cand[i] & bit:
                        cand[i] &= ~bit
                        changed = True
    return changed


def _naked_pairs(cand, g):
    changed = False
    for unit in UNITS:
        empt = [i for i in unit if g[i] == 0]
        pairs = {}
        for i in empt:
            m = cand[i]
            if m.bit_count() == 2:
                pairs.setdefault(m, []).append(i)
        for m, cells in pairs.items():
            if len(cells) >= 2:
                a, b = cells[0], cells[1]
                for i in empt:
                    if i != a and i != b and cand[i] & m:
                        cand[i] &= ~m
                        changed = True
    return changed


def logic_solve(grid, max_tier):
    """Try to solve using techniques up to max_tier. Returns True if solved."""
    g = list(grid)
    cand = [0] * 81
    for i, v in enumerate(g):
        if v == 0:
            m = FULL
            for p in PEERS[i]:
                if g[p]:
                    m &= ~(1 << g[p])
            cand[i] = m
    empties = {i for i, v in enumerate(g) if v == 0}

    def place(i, v):
        g[i] = v
        cand[i] = 0
        bit = 1 << v
        for p in PEERS[i]:
            if g[p] == 0:
                cand[p] &= ~bit
        empties.discard(i)

    while empties:
        for i in empties:
            if cand[i] == 0:
                return False
        progressed = False
        for i in sorted(empties):
            m = cand[i]
            if m and not (m & (m - 1)):
                place(i, m.bit_length() - 1)
                progressed = True
        if progressed:
            continue
        if max_tier >= 2:
            for unit in UNITS:
                present = 0
                for i in unit:
                    if g[i]:
                        present |= 1 << g[i]
                for d in range(1, 10):
                    bit = 1 << d
                    if present & bit:
                        continue
                    spots = [i for i in unit if g[i] == 0 and (cand[i] & bit)]
                    if len(spots) == 1:
                        place(spots[0], d)
                        progressed = True
            if progressed:
                continue
        if max_tier >= 3:
            if _locked_candidates(cand, g) or _naked_pairs(cand, g):
                continue
        return False
    return True


def rate(grid):
    """Return 1..4: minimum technique tier that solves the grid."""
    if logic_solve(grid, 1):
        return 1
    if logic_solve(grid, 2):
        return 2
    if logic_solve(grid, 3):
        return 3
    return 4


def _dig(solution, rng, target_clues):
    """Remove cells while keeping the solution unique, down to target clues."""
    puzzle = list(solution)
    order = list(range(81))
    rng.shuffle(order)
    clues = 81
    for i in order:
        if clues <= target_clues:
            break
        if puzzle[i] == 0:
            continue
        saved = puzzle[i]
        puzzle[i] = 0
        if solution_count(puzzle, 2) != 1:
            puzzle[i] = saved
        else:
            clues -= 1
    return puzzle, clues


@dataclass
class Puzzle:
    puzzle: str  # 81 chars '0'..'9'
    solution: str
    difficulty: str
    tier: int
    clues: int

    def as_dict(self):
        return {
            "difficulty": self.difficulty,
            "tier": self.tier,
            "clues": self.clues,
        }


def _fmt(grid):
    return "".join(str(v) for v in grid)


def generate(difficulty, rng=None):
    """Generate a puzzle for the difficulty. Always returns a unique, valid puzzle."""
    if difficulty not in BANDS:
        raise ValueError(f"difficulty must be one of {DIFFICULTIES}")
    rng = rng or random.Random()
    target, (lo, hi), want = BANDS[difficulty]
    best = None
    for _attempt in range(80):
        sol = _random_solution(rng)
        puzzle, clues = _dig(sol, rng, target)
        tier = rate(puzzle)
        exact = tier == want and lo <= clues <= hi
        expert_ok = difficulty == "expert" and tier >= 3 and clues <= 24
        if exact or expert_ok:
            return Puzzle(_fmt(puzzle), _fmt(sol), difficulty, tier, clues)
        score = abs(tier - want)
        if best is None or score < best[0]:
            best = (score, Puzzle(_fmt(puzzle), _fmt(sol), difficulty, tier, clues))
    return best[1]


def band_ok(difficulty, tier, clues):
    """Test helper: does this puzzle meet its difficulty band?"""
    _, (lo, hi), want = BANDS[difficulty]
    if tier == want and lo <= clues <= hi:
        return True
    return difficulty == "expert" and tier >= 3 and clues <= 24
