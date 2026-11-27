import json

from amr_agent.ollama_agent import OllamaAgent, ollama_tools
from amr_agent.tools import ToolExecutor
from test_agent import FakeBackend


def make_transport(script):
    sent = []

    def transport(payload):
        sent.append(json.loads(json.dumps(payload)))
        return {'message': script.pop(0)}
    return transport, sent


def call(name, args):
    return {'function': {'name': name, 'arguments': args}}


def test_tool_schema_conversion():
    tools = ollama_tools()
    assert all(t['type'] == 'function' and 'parameters' in t['function'] for t in tools)


def test_ollama_loop_executes_tools_and_handles_string_args():
    be = FakeBackend()
    steps = [{'station': 'shelf_1', 'action': 'pick', 'item': 'bolts_m8'},
             {'station': 'packing_station', 'action': 'drop', 'item': 'bolts_m8'}]
    transport, sent = make_transport([
        {'content': '', 'tool_calls': [call('find_item', '{"query": "bolts"}')]},      # JSON-string args
        {'content': '', 'tool_calls': [call('execute_mission', {'steps': steps})]},
        {'content': 'Delivered M8 bolts to packing.'},
    ])
    out = OllamaAgent(ToolExecutor(be), transport=transport).ask('bring bolts')
    assert out['reply'] == 'Delivered M8 bolts to packing.' and out['steps'] == 2
    assert be.missions == [steps]
    tool_msgs = [m for m in sent[1]['messages'] if m['role'] == 'tool']
    assert tool_msgs[0]['tool_name'] == 'find_item' and 'bolts_m8' in tool_msgs[0]['content']
    assert sent[0]['options']['num_ctx'] >= 8192 and sent[0]['options']['temperature'] == 0


def test_ollama_invalid_json_args_are_reported_not_executed():
    be = FakeBackend()
    transport, sent = make_transport([
        {'content': '', 'tool_calls': [call('execute_mission', '{not json')]},
        {'content': 'Sorry, that failed.'},
    ])
    OllamaAgent(ToolExecutor(be), transport=transport).ask('go')
    assert be.missions == []
    assert 'not valid JSON' in [m for m in sent[1]['messages'] if m['role'] == 'tool'][0]['content']
