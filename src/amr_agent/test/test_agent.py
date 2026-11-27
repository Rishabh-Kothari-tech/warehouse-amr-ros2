import json
from types import SimpleNamespace

from amr_agent.llm_agent import ClaudeAgent
from amr_agent.rule_agent import RuleAgent
from amr_agent.tools import TOOLS, ToolExecutor

STATIONS = [
    {'name': 'home', 'type': 'home', 'x': 0, 'y': 0, 'items': []},
    {'name': 'shelf_1', 'type': 'shelf', 'x': 2, 'y': 0.9, 'items': ['bolts_m8', 'nuts_m8', 'washers_m8']},
    {'name': 'shelf_2', 'type': 'shelf', 'x': 2, 'y': -0.9, 'items': ['bearings_6204', 'oil_seals', 'circlips']},
    {'name': 'shelf_4', 'type': 'shelf', 'x': -2, 'y': -0.9, 'items': ['motor_controller', 'hall_sensors', 'bms_board']},
    {'name': 'packing_station', 'type': 'packing', 'x': 3.4, 'y': 0, 'items': []},
    {'name': 'charging_dock', 'type': 'charger', 'x': -3.4, 'y': 0, 'items': []},
]


class FakeBackend:
    def __init__(self, battery=80.0):
        self.battery, self.missions, self.plans = battery, [], []

    def list_stations(self):
        return STATIONS

    def get_status(self):
        return {'state': 'idle', 'battery_pct': self.battery, 'nearest_station': 'home', 'carrying': [], 'capacity': 2}

    def plan_orders(self, orders, start, end):
        self.plans.append(orders)
        steps = [{'station': o['pickup'], 'action': 'pick', 'item': o['item']} for o in orders]
        steps += [{'station': o['dropoff'], 'action': 'drop', 'item': o['item']} for o in orders]
        return {'success': True, 'message': 'ok', 'steps': steps, 'planned_distance_m': 10.0, 'naive_distance_m': 14.0}

    def execute_mission(self, steps, mission_id, on_feedback=None):
        self.missions.append(steps)
        return {'success': True, 'message': f'{mission_id} complete', 'distance_m': 9.5, 'duration_s': 60,
                'battery_pct': self.battery - 14}

    def cancel_mission(self):
        return {'success': True, 'message': 'cancel sent'}


def test_tool_schemas_are_well_formed():
    names = {t['name'] for t in TOOLS}
    assert names == {'get_robot_status', 'list_stations', 'find_item', 'plan_orders', 'execute_mission', 'cancel_mission'}
    for t in TOOLS:
        assert t['input_schema']['type'] == 'object' and t['description']


def test_find_item_fuzzy():
    ex = ToolExecutor(FakeBackend())
    assert ex.find_item('bolts')['matches'][0] == {'sku': 'bolts_m8', 'station': 'shelf_1'}
    assert ex.find_item('BMS board')['matches'][0]['station'] == 'shelf_4'
    assert ex.find_item('bearing')['matches'][0]['sku'] == 'bearings_6204'
    assert ex.find_item('pizza')['matches'] == []


def test_executor_rejects_unknown_station_and_missing_item():
    be = FakeBackend()
    ex = ToolExecutor(be)
    assert 'unknown station' in ex.run('execute_mission', {'steps': [{'station': 'shelf_9', 'action': 'goto'}]})['error']
    assert 'needs an item' in ex.run('execute_mission', {'steps': [{'station': 'shelf_1', 'action': 'pick'}]})['error']
    assert 'action must be' in ex.run('execute_mission', {'steps': [{'station': 'shelf_1', 'action': 'fly'}]})['error']
    assert be.missions == []  # nothing reached the robot


def test_rule_agent_multi_item_delivery_uses_planner():
    be = FakeBackend()
    reply = RuleAgent(ToolExecutor(be)).ask('Bring me bolts and a BMS board')['reply']
    assert be.plans and {o['item'] for o in be.plans[0]} == {'bolts_m8', 'bms_board'}
    assert all(o['dropoff'] == 'packing_station' for o in be.plans[0])
    assert reply.startswith('Done')


def test_rule_agent_low_battery_charges_first():
    be = FakeBackend(battery=15)
    RuleAgent(ToolExecutor(be)).ask('fetch bearings to shelf 4')
    assert be.missions[0][0] == {'station': 'charging_dock', 'action': 'charge', 'item': ''}
    assert be.missions[0][-1]['station'] == 'shelf_4'


def test_rule_agent_goto_and_unknown_item():
    be = FakeBackend()
    RuleAgent(ToolExecutor(be)).ask('go to shelf 2')
    assert be.missions[0] == [{'station': 'shelf_2', 'action': 'goto', 'item': ''}]
    assert 'could not find' in RuleAgent(ToolExecutor(be)).ask('bring pizza')['reply']


class FakeClaude:
    """Scripted stand-in for anthropic.Anthropic: replays tool calls, records what it was sent."""

    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **kw):
        self.calls.append(json.loads(json.dumps(kw['messages'], default=lambda o: o.__dict__)))
        blocks, stop = self.script.pop(0)
        return SimpleNamespace(content=blocks, stop_reason=stop)


def tool_use(i, name, inp):
    return SimpleNamespace(type='tool_use', id=f'tu_{i}', name=name, input=inp)


def text(t):
    return SimpleNamespace(type='text', text=t)


def test_claude_loop_runs_tools_and_returns_results():
    be = FakeBackend()
    steps = [{'station': 'shelf_1', 'action': 'pick', 'item': 'bolts_m8'},
             {'station': 'packing_station', 'action': 'drop', 'item': 'bolts_m8'}]
    client = FakeClaude([
        ([tool_use(1, 'get_robot_status', {}), tool_use(2, 'find_item', {'query': 'bolts'})], 'tool_use'),
        ([text('Delivering bolts.'), tool_use(3, 'execute_mission', {'steps': steps, 'mission_id': 'bolts'})], 'tool_use'),
        ([text('Delivered the M8 bolts to packing. 9.5 m, 60 s, battery 66%.')], 'end_turn'),
    ])
    events = []
    agent = ClaudeAgent(ToolExecutor(be), client=client, on_event=events.append)
    out = agent.ask('bring me some bolts')
    assert out['reply'].startswith('Delivered') and out['steps'] == 3
    assert be.missions == [steps]
    # second request must carry tool_results matched to tool_use ids
    second = client.calls[1]
    results = second[-1]['content']
    assert [r['tool_use_id'] for r in results] == ['tu_1', 'tu_2']
    assert json.loads(results[1]['content'])['matches'][0]['sku'] == 'bolts_m8'
    assert any(e['type'] == 'tool_call' and e['name'] == 'execute_mission' for e in events)


def test_claude_loop_reports_tool_errors_to_model():
    be = FakeBackend()
    client = FakeClaude([
        ([tool_use(1, 'execute_mission', {'steps': [{'station': 'mars', 'action': 'goto'}]})], 'tool_use'),
        ([text('That station does not exist.')], 'end_turn'),
    ])
    out = ClaudeAgent(ToolExecutor(be), client=client).ask('go to mars')
    result = client.calls[1][-1]['content'][0]
    assert result['is_error'] is True and 'unknown station' in result['content']
    assert be.missions == [] and out['reply']
