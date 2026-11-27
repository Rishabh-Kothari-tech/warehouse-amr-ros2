import json

from amr_agent.intent_agent import LocalIntentAgent
from amr_agent.tools import ToolExecutor
from test_agent import FakeBackend


def agent_with(intent, battery=80.0):
    be = FakeBackend(battery=battery)
    sent = []

    def transport(payload):
        sent.append(payload)
        return {'message': {'content': json.dumps(intent)}}
    return LocalIntentAgent(ToolExecutor(be), transport=transport), be, sent


def test_schema_constrains_skus_and_stations_from_live_inventory():
    agent, be, sent = agent_with({'intent': 'status', 'items': [], 'unknown_items': [], 'destination': ''})
    agent.ask('battery?')
    schema = sent[0]['format']
    assert 'bms_board' in schema['properties']['items']['items']['enum']
    assert 'charging_dock' in schema['properties']['destination']['enum']
    assert be.missions == []


def test_deliver_two_items_uses_planner_and_default_destination():
    agent, be, _ = agent_with({'intent': 'deliver', 'items': ['bearings_6204', 'oil_seals'],
                               'unknown_items': [], 'destination': ''})
    out = agent.ask('I need a bearing and oil seals')
    assert {o['item'] for o in be.plans[0]} == {'bearings_6204', 'oil_seals'}
    assert all(o['dropoff'] == 'packing_station' for o in be.plans[0])
    assert out['reply'].startswith('Done')


def test_low_battery_charges_first_and_unknown_item_does_not_move():
    agent, be, _ = agent_with({'intent': 'deliver', 'items': ['circlips'], 'unknown_items': [], 'destination': ''},
                              battery=18)
    agent.ask('circlips please')
    assert be.missions[0][0]['action'] == 'charge' and be.missions[0][-1]['item'] == 'circlips'
    agent2, be2, _ = agent_with({'intent': 'deliver', 'items': [], 'unknown_items': ['pizza'], 'destination': ''})
    assert 'not stocked' in agent2.ask('bring pizza')['reply'] and be2.missions == []


def test_model_output_outside_schema_is_sanitised():
    agent, be, _ = agent_with({'intent': 'deliver', 'items': ['plutonium', 'bolts_m8', 'bolts_m8'],
                               'unknown_items': [], 'destination': 'mars'})
    agent.ask('bring bolts')
    assert be.missions[0] == [{'station': 'shelf_1', 'action': 'pick', 'item': 'bolts_m8'},
                              {'station': 'packing_station', 'action': 'drop', 'item': 'bolts_m8'}]


def test_grounding_check():
    from amr_agent.intent_agent import grounded
    assert grounded('wiring_harness', "we're out of wiring harnesses")
    assert grounded('bearings_6204', 'I need a bearing')
    assert grounded('bms_board', 'bring the BMS')
    assert not grounded('motor_controller', 'send the robot over to the charger and top it up')
    assert not grounded('bms_board', 'now send the robot to the charger')


def test_verifier_retries_and_never_executes_hallucinated_items():
    be = FakeBackend()
    replies = [{'intent': 'deliver', 'items': ['motor_controller', 'bms_board'], 'unknown_items': [],
                'destination': 'charging_dock'},
               {'intent': 'charge', 'items': [], 'unknown_items': [], 'destination': 'charging_dock'}]
    sent = []

    def transport(payload):
        sent.append(payload)
        return {'message': {'content': json.dumps(replies.pop(0))}}
    out = LocalIntentAgent(ToolExecutor(be), transport=transport).ask('now send the robot over to the charger and top it up')
    assert len(sent) == 2 and 'never mentions' in sent[1]['messages'][-1]['content']
    assert be.missions == [[{'station': 'charging_dock', 'action': 'charge', 'item': ''}]]
    assert out['reply'].startswith('Done')


def test_verifier_refuses_to_move_if_model_insists():
    be = FakeBackend()
    bad = {'intent': 'deliver', 'items': ['motor_controller'], 'unknown_items': [], 'destination': 'charging_dock'}
    agent = LocalIntentAgent(ToolExecutor(be), transport=lambda p: {'message': {'content': json.dumps(bad)}})
    assert 'did not move' in agent.ask('top it up please')['reply'] and be.missions == []


def test_stated_destination_extraction():
    from amr_agent.intent_agent import stated_destination
    assert stated_destination('brake pads and battery cells to shipping') == 'shipping_dock'
    assert stated_destination('I need bolts and bearings at packing') == 'packing_station'
    assert stated_destination('bring bolts from rack A1 to packing') == 'packing_station'
    assert stated_destination('go to rack B2') == 'rack_B2'
    assert stated_destination('head home') is None and stated_destination('bring me bolts') is None


def test_stated_destination_overrides_model():
    agent, be, _ = agent_with({'intent': 'deliver', 'items': ['bms_board', 'hall_sensors'], 'unknown_items': [],
                               'destination': 'packing_station'})
    agent.ask('bms board and hall sensors to the charging dock')
    assert all(o['dropoff'] == 'charging_dock' for o in be.plans[0])


def test_unstated_destination_is_dropped_and_defaults_to_packing():
    agent, be, _ = agent_with({'intent': 'deliver', 'items': ['bolts_m8'], 'unknown_items': [], 'destination': 'shelf_1'})
    agent.ask('bring me some bolts')
    assert be.missions[0][-1] == {'station': 'packing_station', 'action': 'drop', 'item': 'bolts_m8'}


def test_charge_intent_needs_charge_words_and_not_a_question():
    for text in ('bring me a laptop charger', 'is the robot charging right now?'):
        agent, be, _ = agent_with({'intent': 'charge', 'items': [], 'unknown_items': [], 'destination': 'charging_dock'})
        agent.ask(text)
        assert be.missions == [], text
    agent, be, _ = agent_with({'intent': 'charge', 'items': [], 'unknown_items': [], 'destination': ''})
    agent.ask('the robot looks low, top it up')
    assert be.missions[0][0]['action'] == 'charge'
