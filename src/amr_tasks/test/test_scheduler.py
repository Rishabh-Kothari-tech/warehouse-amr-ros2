import itertools
import math

import pytest

from amr_tasks.scheduler import Order, _is_feasible, _route_cost, naive_plan, optimal_plan

POS = {
    'home': (0.0, 0.0), 'shelf_1': (2.0, 0.9), 'shelf_2': (2.0, -0.9), 'shelf_3': (-2.0, 0.9),
    'shelf_4': (-2.0, -0.9), 'packing': (3.4, 0.0), 'charger': (-3.4, 0.0),
}


def euclid(a, b):
    (x1, y1), (x2, y2) = POS[a], POS[b]
    return math.hypot(x2 - x1, y2 - y1)


def brute_force(orders, start, end, capacity):
    n = len(orders)
    stops = [(i, True) for i in range(n)] + [(i, False) for i in range(n)]
    best = math.inf
    for perm in itertools.permutations(stops):
        if _is_feasible(perm, n, capacity):
            best = min(best, _route_cost(orders, perm, start, end, euclid))
    return best


ORDERS = [
    Order('o1', 'bolts', 'shelf_3', 'packing'),
    Order('o2', 'bearings', 'shelf_2', 'packing'),
    Order('o3', 'sensors', 'shelf_4', 'charger'),
]


@pytest.mark.parametrize('capacity', [1, 2, 3])
def test_exact_matches_brute_force(capacity):
    steps, cost, method = optimal_plan(ORDERS, 'home', 'home', euclid, capacity=capacity)
    assert method.startswith('exact')
    assert cost == pytest.approx(brute_force(ORDERS, 'home', 'home', capacity))


def test_never_worse_than_naive_and_valid():
    _, naive = naive_plan(ORDERS, 'home', 'home', euclid)
    steps, cost, _ = optimal_plan(ORDERS, 'home', 'home', euclid, capacity=2)
    assert cost <= naive + 1e-9
    # every item picked before it is dropped, capacity respected
    load, carrying = 0, set()
    for s in steps:
        if s.action == 'pick':
            carrying.add(s.item)
            load += 1
            assert load <= 2
        elif s.action == 'drop':
            assert s.item in carrying
            carrying.remove(s.item)
            load -= 1
    assert not carrying and steps[-1].action == 'goto' and steps[-1].station == 'home'


def test_capacity_two_beats_naive_when_orders_share_dropoff():
    _, naive = naive_plan(ORDERS[:2], 'home', None, euclid)
    _, cost, _ = optimal_plan(ORDERS[:2], 'home', None, euclid, capacity=2)
    assert cost < naive


def test_large_instance_uses_heuristic_and_is_feasible():
    names = ['shelf_1', 'shelf_2', 'shelf_3', 'shelf_4']
    orders = [Order(f'o{i}', f'item{i}', names[i % 4], 'packing' if i % 2 else 'charger') for i in range(9)]
    steps, cost, method = optimal_plan(orders, 'home', None, euclid, capacity=2, exact_limit=7)
    assert method.startswith('greedy')
    assert sum(1 for s in steps if s.action == 'pick') == 9
    _, naive = naive_plan(orders, 'home', None, euclid)
    assert cost <= naive + 1e-9


def test_empty_orders():
    steps, cost, _ = optimal_plan([], 'home', 'charger', euclid)
    assert [s.station for s in steps] == ['charger'] and cost == pytest.approx(3.4)
