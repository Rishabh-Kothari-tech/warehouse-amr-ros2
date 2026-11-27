"""Benchmark the warehouse agents on natural-language requests, without moving the robot.

    ros2 run amr_agent evaluate              # rule-based and (if a key is configured) Claude
    ros2 run amr_agent evaluate --offline    # rule-based only

Each case runs against SimBackend, an in-memory warehouse that executes missions instantly
and records them, so results are deterministic and cost nothing in robot time. A case passes
when the missions the agent launched move exactly the expected items to the expected
station, charge first when the battery requires it, and do nothing when nothing should happen.
"""
import argparse
import json
import math
import sys
import time

from amr_agent.common import build_agent
from amr_agent.tools import ToolExecutor

STATIONS = [
    {'name': 'home', 'type': 'home', 'x': 0.0, 'y': 0.0, 'items': []},
    {'name': 'shelf_1', 'type': 'shelf', 'x': 2.0, 'y': 0.9, 'items': ['bolts_m8', 'nuts_m8', 'washers_m8']},
    {'name': 'shelf_2', 'type': 'shelf', 'x': 2.0, 'y': -0.9, 'items': ['bearings_6204', 'oil_seals', 'circlips']},
    {'name': 'shelf_3', 'type': 'shelf', 'x': -2.0, 'y': 0.9, 'items': ['cable_ties', 'wiring_harness', 'connectors']},
    {'name': 'shelf_4', 'type': 'shelf', 'x': -2.0, 'y': -0.9, 'items': ['motor_controller', 'hall_sensors', 'bms_board']},
    {'name': 'packing_station', 'type': 'packing', 'x': 3.4, 'y': 0.0, 'items': []},
    {'name': 'charging_dock', 'type': 'charger', 'x': -3.4, 'y': 0.0, 'items': []},
]
POS = {s['name']: (s['x'], s['y']) for s in STATIONS}

# (request, battery %, expected deliveries {sku: destination} or None for "no mission", must_charge_first)
CASES = [
    ('bring me some bolts', 90, {'bolts_m8': 'packing_station'}, False),
    ('I need a bearing and oil seals at packing', 90, {'bearings_6204': 'packing_station', 'oil_seals': 'packing_station'}, False),
    ('fetch the BMS board and the hall sensors to shelf 1', 90, {'bms_board': 'shelf_1', 'hall_sensors': 'shelf_1'}, False),
    ("we're out of wiring harnesses on the line, bring one to packing", 90, {'wiring_harness': 'packing_station'}, False),
    ('get washers, nuts and bolts', 90, {'washers_m8': 'packing_station', 'nuts_m8': 'packing_station',
                                        'bolts_m8': 'packing_station'}, False),
    ('circlips to the packing station please', 18, {'circlips': 'packing_station'}, True),
    ('how much battery is left?', 90, None, False),
    ('bring me a pizza', 90, None, False),
    ('send the robot to shelf three', 90, {'__goto__': 'shelf_3'}, False),
    ('the robot looks low, top it up', 30, {'__charge__': 'charging_dock'}, False),
]


class SimBackend:
    """In-memory warehouse: instant missions, battery drain 1.5%/m on straight-line distance."""

    def __init__(self, battery):
        self.battery, self.missions, self.pos, self.carrying = float(battery), [], 'home', []

    def list_stations(self):
        return STATIONS

    def get_status(self):
        return {'state': 'idle', 'battery_pct': round(self.battery, 1), 'nearest_station': self.pos,
                'carrying': list(self.carrying), 'capacity': 2, 'last_message': 'ready'}

    def _d(self, a, b):
        return math.dist(POS[a], POS[b])

    def plan_orders(self, orders, start, end):
        from amr_tasks.scheduler import Order, naive_plan, optimal_plan
        os_ = [Order(str(i), o['item'], o['pickup'], o['dropoff']) for i, o in enumerate(orders)]
        for o in os_:
            if o.pickup not in POS or o.dropoff not in POS:
                return {'success': False, 'message': f'unknown station in {o}'}
        steps, cost, method = optimal_plan(os_, self.pos, end or None, self._d, capacity=2)
        _, naive = naive_plan(os_, self.pos, end or None, self._d)
        return {'success': True, 'message': f'{method}: {cost:.1f} m vs {naive:.1f} m',
                'steps': [{'station': s.station, 'action': s.action, 'item': s.item} for s in steps],
                'planned_distance_m': round(cost, 2), 'naive_distance_m': round(naive, 2)}

    def execute_mission(self, steps, mission_id='', on_feedback=None):
        carrying, dist, here = list(self.carrying), 0.0, self.pos
        stock = {s['name']: s['items'] for s in STATIONS}
        for i, s in enumerate(steps, 1):  # same validation rules as warehouse_manager
            if s['action'] == 'pick':
                if s['item'] not in stock[s['station']]:
                    return {'success': False, 'message': f'step {i}: {s["item"]} not stocked at {s["station"]}'}
                if len(carrying) >= 2:
                    return {'success': False, 'message': f'step {i}: over capacity'}
                carrying.append(s['item'])
            elif s['action'] == 'drop':
                if s['item'] not in carrying:
                    return {'success': False, 'message': f'step {i}: not carrying {s["item"]}'}
                carrying.remove(s['item'])
            elif s['action'] == 'charge' and s['station'] != 'charging_dock':
                return {'success': False, 'message': f'step {i}: not a charger'}
        for s in steps:
            dist += self._d(here, s['station'])
            here = s['station']
            self.battery = 100.0 if s['action'] == 'charge' else self.battery - self._d(self.pos, s['station']) * 1.5
            self.pos = here
        self.carrying = carrying
        self.missions.append(steps)
        return {'success': True, 'message': f'{mission_id or "mission"} complete', 'distance_m': round(dist, 2),
                'duration_s': round(dist / 0.2 + 3 * len(steps)), 'battery_pct': round(self.battery, 1)}

    def cancel_mission(self):
        return {'success': True, 'message': 'no mission running'}


def score(backend, expected, must_charge):
    steps = [s for m in backend.missions for s in m]
    if expected is None:
        return (not steps), 'no mission' if not steps else f'unexpected mission {steps}'
    if '__goto__' in expected:
        ok = bool(steps) and steps[-1]['station'] == expected['__goto__'] and all(s['action'] == 'goto' for s in steps)
        return ok, f'goto {[s["station"] for s in steps]}'
    if '__charge__' in expected:
        ok = any(s['action'] == 'charge' and s['station'] == 'charging_dock' for s in steps)
        return ok, f'charge={ok}'
    delivered = {s['item']: s['station'] for s in steps if s['action'] == 'drop'}
    charged_first = bool(steps) and steps[0]['action'] == 'charge'
    ok = delivered == expected and (charged_first if must_charge else True)
    detail = f'delivered {delivered}' + (f', charged first={charged_first}' if must_charge else '')
    return ok, detail


def run(agent_factory, label, verbose):
    passed, rows, t0 = 0, [], time.monotonic()
    for text, battery, expected, must_charge in CASES:
        backend = SimBackend(battery)
        agent = agent_factory(backend)
        try:
            out = agent.ask(text)
            ok, detail = score(backend, expected, must_charge)
            reply = out['reply']
        except Exception as exc:  # an agent crash is a failed case, not a crashed benchmark
            ok, detail, reply = False, f'{type(exc).__name__}: {exc}', ''
        passed += ok
        rows.append({'request': text, 'pass': ok, 'detail': detail, 'reply': reply})
        print(f'  [{"PASS" if ok else "FAIL"}] {text!r:70.70} {detail}', flush=True)
        if verbose:
            print(f'         reply: {reply[:200]}')
    print(f'{label}: {passed}/{len(CASES)} passed in {time.monotonic() - t0:.0f} s\n', flush=True)
    return {'agent': label, 'passed': passed, 'total': len(CASES), 'cases': rows}


def main(argv=None):
    ap = argparse.ArgumentParser(description='Evaluate warehouse agents on natural-language requests')
    ap.add_argument('--offline', action='store_true', help='rule-based agent only')
    ap.add_argument('--model', help='Claude model id')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--json', help='write results to this file')
    args, _ = ap.parse_known_args(argv)

    results = [run(lambda be: build_agent(be, offline=True)[0], 'rule-based agent', args.verbose)]
    if not args.offline:
        probe, mode = build_agent(SimBackend(90), model=args.model)
        if mode.startswith('Claude'):
            results.append(run(lambda be: build_agent(be, model=args.model)[0], mode, args.verbose))
        else:
            print(f'Skipping LLM agent: {mode}')
    if args.json:
        with open(args.json, 'w') as f:
            json.dump(results, f, indent=2)
    return 0


if __name__ == '__main__':
    sys.exit(main())
