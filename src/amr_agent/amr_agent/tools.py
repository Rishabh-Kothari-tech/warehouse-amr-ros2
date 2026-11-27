"""Tools the agent may call, and the dispatcher that runs them against a warehouse backend.

The backend is anything implementing:
    list_stations() -> list[dict(name, type, x, y, yaw, items)]
    get_status()    -> dict
    plan_orders(orders: list[dict], start_station: str, end_station: str) -> dict
    execute_mission(steps: list[dict], mission_id: str, on_feedback=None) -> dict
    cancel_mission() -> dict
In the running system that is amr_agent.ros_client.WarehouseClient (ROS services/actions of
amr_tasks/warehouse_manager); in unit tests it is a fake. Pure Python, no ROS imports.

The LLM never talks to Nav2 directly. It can only call these tools, every argument is
checked here, and the warehouse manager validates missions again before the robot moves.
"""
import json
import re
from typing import Callable, Dict, List, Optional

TOOLS: List[dict] = [
    {
        'name': 'get_robot_status',
        'description': 'Current robot state: pose in the map frame, battery %, state (idle/navigating/picking/'
                       'dropping/charging/error), nearest station, items being carried, capacity, odometer and last '
                       'message. Call this before planning any mission.',
        'input_schema': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'list_stations',
        'description': 'All warehouse stations (shelves, packing station, charging dock, home) with their map '
                       'coordinates and, for shelves, the SKUs stocked there.',
        'input_schema': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'find_item',
        'description': 'Search the shelf inventory for an item described in natural language (e.g. "bolts", '
                       '"bearing", "BMS"). Returns matching SKUs and the station that stocks each. Use this to map '
                       'what a person asks for to exact SKU and station names.',
        'input_schema': {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']},
    },
    {
        'name': 'plan_orders',
        'description': 'Optimise the sequence for one or more transport orders. Uses real Nav2 path lengths and '
                       'respects pickup-before-dropoff and the carrying capacity. Returns ordered mission steps plus '
                       'planned vs one-at-a-time distance. Use for ANY request with more than one item, then pass '
                       'the returned steps to execute_mission.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'orders': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'item': {'type': 'string', 'description': 'exact SKU'},
                            'pickup': {'type': 'string', 'description': 'station that stocks the SKU'},
                            'dropoff': {'type': 'string', 'description': 'destination station'},
                        },
                        'required': ['item', 'pickup', 'dropoff'],
                    },
                },
                'end_station': {'type': 'string', 'description': 'optional station to finish at, e.g. charging_dock'},
            },
            'required': ['orders'],
        },
    },
    {
        'name': 'execute_mission',
        'description': 'Run a mission on the robot and wait for it to finish. Steps run in order: drive to the '
                       'station, then do the action. Actions: goto, pick (item required, must be stocked there), '
                       'drop (item required, must be carried), charge (charging_dock only). Returns success, '
                       'message, distance, duration and final battery.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'steps': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'station': {'type': 'string'},
                            'action': {'type': 'string', 'enum': ['goto', 'pick', 'drop', 'charge']},
                            'item': {'type': 'string'},
                        },
                        'required': ['station', 'action'],
                    },
                },
                'mission_id': {'type': 'string', 'description': 'short human-readable id'},
            },
            'required': ['steps'],
        },
    },
    {
        'name': 'cancel_mission',
        'description': 'Cancel the mission currently running, if any.',
        'input_schema': {'type': 'object', 'properties': {}},
    },
]

ACTIONS = {'goto', 'pick', 'drop', 'charge'}


def _tokens(text: str):
    return [t for t in re.split(r'[^a-z0-9]+', text.lower()) if t]


class ToolExecutor:
    def __init__(self, backend, on_feedback: Optional[Callable[[dict], None]] = None):
        self.backend = backend
        self.on_feedback = on_feedback
        self._stations_cache: Optional[List[dict]] = None

    # -- helpers --------------------------------------------------------------
    def stations(self) -> List[dict]:
        if self._stations_cache is None:
            self._stations_cache = self.backend.list_stations()
        return self._stations_cache

    def station_names(self):
        return [s['name'] for s in self.stations()]

    def find_item(self, query: str) -> dict:
        q = _tokens(query)
        q_stems = {t.rstrip('s') for t in q}
        matches = []
        for s in self.stations():
            for sku in s.get('items', []):
                sku_toks = _tokens(sku)
                score = sum(1 for t in q_stems if any(st.startswith(t) or t.startswith(st.rstrip('s'))
                                                      for st in sku_toks))
                if score:
                    matches.append({'sku': sku, 'station': s['name'], 'score': score})
        matches.sort(key=lambda m: -m['score'])
        return {'query': query, 'matches': [{'sku': m['sku'], 'station': m['station']} for m in matches]}

    # -- dispatch -------------------------------------------------------------
    def run(self, name: str, args: Dict) -> dict:
        args = args or {}
        try:
            if name == 'get_robot_status':
                return self.backend.get_status()
            if name == 'list_stations':
                return {'stations': self.stations()}
            if name == 'find_item':
                return self.find_item(str(args.get('query', '')))
            if name == 'plan_orders':
                orders = args.get('orders') or []
                if not isinstance(orders, list) or not orders:
                    return {'error': 'orders must be a non-empty list'}
                bad = [o for o in orders if not isinstance(o, dict) or not {'item', 'pickup', 'dropoff'} <= set(o)]
                if bad:
                    return {'error': 'each order needs item, pickup and dropoff'}
                return self.backend.plan_orders(orders, '', str(args.get('end_station', '') or ''))
            if name == 'execute_mission':
                steps = args.get('steps') or []
                if not isinstance(steps, list) or not steps:
                    return {'error': 'steps must be a non-empty list'}
                known = set(self.station_names())
                for i, s in enumerate(steps, 1):
                    if not isinstance(s, dict) or s.get('station') not in known:
                        return {'error': f'step {i}: unknown station {s.get("station") if isinstance(s, dict) else s!r}; '
                                         f'known stations: {sorted(known)}'}
                    if s.get('action') not in ACTIONS:
                        return {'error': f'step {i}: action must be one of {sorted(ACTIONS)}'}
                    if s['action'] in ('pick', 'drop') and not s.get('item'):
                        return {'error': f'step {i}: {s["action"]} needs an item'}
                clean = [{'station': s['station'], 'action': s['action'], 'item': s.get('item', '') or ''} for s in steps]
                return self.backend.execute_mission(clean, str(args.get('mission_id', '') or ''), self.on_feedback)
            if name == 'cancel_mission':
                return self.backend.cancel_mission()
            return {'error': f'unknown tool {name}'}
        except Exception as exc:  # surface backend failures to the model instead of crashing the loop
            return {'error': f'{type(exc).__name__}: {exc}'}


def to_json(result) -> str:
    return json.dumps(result, default=str)
