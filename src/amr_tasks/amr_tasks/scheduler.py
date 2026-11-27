"""Multi-order pickup-and-delivery sequencing for a single AMR.

Pure Python (no ROS imports) so it can be unit-tested anywhere. The distance function is
injected: in the running system it is the length of the Nav2 global plan between two
stations, so the optimiser reasons about real drivable distance around shelves, not
straight lines.

Problem: given orders (item, pickup station, drop-off station), a start location, an
optional end location and a carrying capacity, find the order of pick/drop stops that
minimises total travel, subject to
  * every item is picked before it is dropped, and
  * the robot never carries more than `capacity` items.

Small instances (the common case: a handful of orders) are solved exactly with a
depth-first branch-and-bound search with state dominance pruning. Larger ones fall back
to a greedy nearest-feasible-stop heuristic followed by a 2-opt-style local improvement.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

DistanceFn = Callable[[str, str], float]


@dataclass(frozen=True)
class Order:
    order_id: str
    item: str
    pickup: str
    dropoff: str


@dataclass(frozen=True)
class Step:
    station: str
    action: str  # goto | pick | drop | charge
    item: str = ''


# A stop is (order index, is_pickup)
Stop = Tuple[int, bool]


def _stop_station(orders: Sequence[Order], stop: Stop) -> str:
    i, is_pick = stop
    return orders[i].pickup if is_pick else orders[i].dropoff


def _route_cost(orders: Sequence[Order], stops: Sequence[Stop], start: str,
                end: Optional[str], dist: DistanceFn) -> float:
    total, here = 0.0, start
    for stop in stops:
        nxt = _stop_station(orders, stop)
        total += dist(here, nxt)
        here = nxt
    if end:
        total += dist(here, end)
    return total


def _is_feasible(stops: Sequence[Stop], n: int, capacity: int) -> bool:
    picked, dropped, load = [False] * n, [False] * n, 0
    for i, is_pick in stops:
        if is_pick:
            if picked[i] or load >= capacity:
                return False
            picked[i], load = True, load + 1
        else:
            if not picked[i] or dropped[i]:
                return False
            dropped[i], load = True, load - 1
    return all(picked) and all(dropped)


def _to_steps(orders: Sequence[Order], stops: Sequence[Stop], end: Optional[str]) -> List[Step]:
    steps = [Step(_stop_station(orders, s), 'pick' if s[1] else 'drop', orders[s[0]].item) for s in stops]
    if end:
        steps.append(Step(end, 'goto'))
    return steps


def naive_plan(orders: Sequence[Order], start: str, end: Optional[str],
               dist: DistanceFn) -> Tuple[List[Step], float]:
    """Baseline: serve orders one at a time in the given (FIFO) order."""
    stops: List[Stop] = []
    for i in range(len(orders)):
        stops += [(i, True), (i, False)]
    return _to_steps(orders, stops, end), _route_cost(orders, stops, start, end, dist)


def _exact(orders: Sequence[Order], start: str, end: Optional[str], dist: DistanceFn,
           capacity: int) -> List[Stop]:
    n = len(orders)
    full = (1 << n) - 1
    best: Dict[str, object] = {'cost': float('inf'), 'stops': []}
    # dominance table: (location, picked_mask, dropped_mask) -> cheapest cost seen
    seen: Dict[Tuple[str, int, int], float] = {}

    # admissible lower bound for the remaining route: the farthest single remaining leg
    def lower_bound(here: str, picked: int, dropped: int) -> float:
        lb = 0.0
        for i in range(n):
            if not dropped >> i & 1:
                target = orders[i].dropoff if picked >> i & 1 else orders[i].pickup
                lb = max(lb, dist(here, target))
        return lb

    def dfs(here: str, picked: int, dropped: int, load: int, cost: float, path: List[Stop]):
        if cost + lower_bound(here, picked, dropped) >= best['cost']:
            return
        key = (here, picked, dropped)
        if seen.get(key, float('inf')) <= cost:
            return
        seen[key] = cost
        if dropped == full:
            total = cost + (dist(here, end) if end else 0.0)
            if total < best['cost']:
                best['cost'], best['stops'] = total, list(path)
            return
        # candidate moves, nearest first so good solutions are found early (tighter bound)
        moves = []
        for i in range(n):
            if picked >> i & 1:
                if not dropped >> i & 1:
                    moves.append((dist(here, orders[i].dropoff), i, False))
            elif load < capacity:
                moves.append((dist(here, orders[i].pickup), i, True))
        for d, i, is_pick in sorted(moves):
            nxt = orders[i].pickup if is_pick else orders[i].dropoff
            path.append((i, is_pick))
            if is_pick:
                dfs(nxt, picked | 1 << i, dropped, load + 1, cost + d, path)
            else:
                dfs(nxt, picked, dropped | 1 << i, load - 1, cost + d, path)
            path.pop()

    dfs(start, 0, 0, 0, 0.0, [])
    return best['stops']  # type: ignore[return-value]


def _greedy(orders: Sequence[Order], start: str, dist: DistanceFn, capacity: int) -> List[Stop]:
    n = len(orders)
    picked, dropped, load, here, stops = [False] * n, [False] * n, 0, start, []
    while not all(dropped):
        cands = []
        for i in range(n):
            if picked[i] and not dropped[i]:
                cands.append((dist(here, orders[i].dropoff), i, False))
            elif not picked[i] and load < capacity:
                cands.append((dist(here, orders[i].pickup), i, True))
        _, i, is_pick = min(cands)
        stops.append((i, is_pick))
        if is_pick:
            picked[i], load, here = True, load + 1, orders[i].pickup
        else:
            dropped[i], load, here = True, load - 1, orders[i].dropoff
    return stops


def _improve(orders, stops, start, end, dist, capacity) -> List[Stop]:
    """Relocate single stops while it reduces cost and stays feasible."""
    best, best_cost, improved = list(stops), _route_cost(orders, stops, start, end, dist), True
    n = len(orders)
    while improved:
        improved = False
        for a in range(len(best)):
            for b in range(len(best)):
                if a == b:
                    continue
                cand = list(best)
                cand.insert(b, cand.pop(a))
                if not _is_feasible(cand, n, capacity):
                    continue
                c = _route_cost(orders, cand, start, end, dist)
                if c + 1e-9 < best_cost:
                    best, best_cost, improved = cand, c, True
    return best


def optimal_plan(orders: Sequence[Order], start: str, end: Optional[str], dist: DistanceFn,
                 capacity: int = 2, exact_limit: int = 7) -> Tuple[List[Step], float, str]:
    """Return (steps, total_distance, method)."""
    if not orders:
        steps = [Step(end, 'goto')] if end else []
        return steps, (dist(start, end) if end else 0.0), 'trivial'
    if capacity < 1:
        raise ValueError('capacity must be >= 1')
    if len(orders) <= exact_limit:
        stops, method = _exact(orders, start, end, dist, capacity), 'exact branch-and-bound'
    else:
        stops = _improve(orders, _greedy(orders, start, dist, capacity), start, end, dist, capacity)
        method = 'greedy + local search'
    assert _is_feasible(stops, len(orders), capacity), 'internal error: infeasible plan'
    return _to_steps(orders, stops, end), _route_cost(orders, stops, start, end, dist), method
