"""Hybrid agent for small on-device models: the LLM only parses language, code does the rest.

Free-form multi-step tool calling is unreliable for ~3B-parameter models (they skip tools,
hallucinate completed missions, or pick wrong SKUs). This agent asks the model for ONE thing,
a structured intent, using Ollama's grammar-constrained decoding against a JSON schema that is
generated from the live inventory, so the model cannot emit an unknown SKU or station. Planning
(SKU lookup, route optimisation), the battery rule and execution are deterministic code shared
with the rule-based agent.

One LLM call per request (vs 4-8 for a tool loop), so it is also much faster on a laptop GPU.
"""
import json
import re
import time

from amr_agent.ollama_agent import DEFAULT_OLLAMA_MODEL, OLLAMA_URL
from amr_agent.rule_agent import LOW_BATTERY, RuleAgent

INTENTS = ['deliver', 'goto', 'charge', 'status', 'inventory', 'cancel', 'unknown']


def _words(text):
    return [w for w in re.split(r'[^a-z0-9]+', text.lower()) if len(w) >= 3 and not w.isdigit()]


def grounded(sku, text):
    """True if the request actually mentions the product: some word of the SKU (ignoring sizes/part numbers)
    shares a stem with a word of the request ("harnesses" ~ wiring_harness, "a bearing" ~ bearings_6204)."""
    req = _words(text)
    for k in _words(sku.replace('_', ' ')):
        if k in ('m8',):
            continue
        for t in req:
            n = max(3, min(len(k), len(t)) - 2)
            if k[:n] == t[:n]:
                return True
    return False

PROMPT = """You convert a warehouse worker's request for a mobile robot into a JSON intent.

Intents:
- deliver: move one or more products to a station (words like bring, fetch, get, need, send me, restock)
- goto: drive the robot somewhere without carrying anything (go to, send the robot to, park at)
- charge: charge / top up / recharge the battery
- status: questions about the robot (battery, where is it, what is it doing)
- inventory: questions about which products are stocked where
- cancel: stop / abort the current job
- unknown: anything else

Product catalogue (sku: shelf):
{catalogue}

Stations: {stations}

Rules:
- items: the catalogue SKUs the person asked for, once each. Map loose wording to the matching SKU
  ("a bearing" -> bearings_6204, "BMS" -> bms_board, "harnesses" -> wiring_harness).
- unknown_items: anything requested that is NOT in the catalogue (e.g. "pizza"). Never force it onto a SKU.
- destination: for deliver, where the items should go ("" if not said); for goto, the station to drive to;
  otherwise "". "shelf three" means shelf_3, "packing" means packing_station, "charger"/"dock" means charging_dock.
- If the request is a delivery and also says to park/charge afterwards, still use intent deliver."""


class LocalIntentAgent(RuleAgent):
    def __init__(self, executor, model=DEFAULT_OLLAMA_MODEL, url=OLLAMA_URL, on_event=None, transport=None):
        super().__init__(executor, on_event=on_event)
        self.model, self.url = model, url
        self.transport = transport or self._post

    def _post(self, payload):
        import urllib.request
        req = urllib.request.Request(f'{self.url}/api/chat', data=json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r)

    def parse(self, text, stations, retry_feedback=None, previous=None):
        skus = sorted({sku for s in stations for sku in s.get('items', [])})
        names = [s['name'] for s in stations]
        catalogue = '\n'.join(f'  {sku}: {s["name"]}' for s in stations for sku in s.get('items', []))
        schema = {
            'type': 'object',
            'properties': {
                'intent': {'type': 'string', 'enum': INTENTS},
                'items': {'type': 'array', 'items': {'type': 'string', 'enum': skus}},
                'unknown_items': {'type': 'array', 'items': {'type': 'string'}},
                'destination': {'type': 'string', 'enum': names + ['']},
            },
            'required': ['intent', 'items', 'unknown_items', 'destination'],
        }
        payload = {'model': self.model, 'stream': False, 'format': schema,
                   'options': {'temperature': 0, 'num_ctx': 4096},
                   'messages': [{'role': 'system', 'content': PROMPT.format(catalogue=catalogue, stations=', '.join(names))},
                                {'role': 'user', 'content': text}]}
        if retry_feedback:
            payload['messages'] += [{'role': 'assistant', 'content': json.dumps(previous)},
                                    {'role': 'user', 'content': retry_feedback}]
        intent = json.loads(self.transport(payload)['message']['content'])
        # defence in depth: the schema should guarantee this, but never trust model output blindly
        intent['items'] = [i for i in dict.fromkeys(intent.get('items', [])) if i in skus]
        if intent.get('destination') not in names:
            intent['destination'] = ''
        if intent.get('intent') not in INTENTS:
            intent['intent'] = 'unknown'
        intent['unknown_items'] = [u for u in intent.get('unknown_items', [])
                                   if str(u).strip().lower() not in ('', 'none', 'n/a', 'null', 'nothing')]
        return intent

    def ask(self, text: str) -> dict:
        t0, self.trace = time.monotonic(), []
        try:
            reply = self._handle_intent(text)
        except Exception as exc:  # model server down, bad JSON, etc.
            reply = f'Could not process that request: {type(exc).__name__}: {exc}'
        return {'reply': reply, 'trace': self.trace, 'steps': len(self.trace), 'seconds': round(time.monotonic() - t0, 1)}

    def _handle_intent(self, text):
        stations = self._tool('list_stations')['stations']
        intent = self.parse(text, stations)
        self.on_event({'type': 'intent', 'intent': intent})
        self.trace.append({'tool': '(llm intent parse)', 'input': text, 'output': intent})
        # Verifier: the model proposes, code checks. Every product must be mentioned in the request.
        ungrounded = [i for i in intent['items'] if not grounded(i, text)]
        if ungrounded:
            feedback = (f'Your answer lists products the request never mentions: {", ".join(ungrounded)}. '
                        'Re-read the request. Only list products the person actually named; if they named none, '
                        'it is not a delivery (it may be goto, charge or status). Answer again.')
            self.on_event({'type': 'verifier', 'rejected': ungrounded})
            first = intent
            intent = self.parse(text, stations, retry_feedback=feedback, previous=first)
            self.on_event({'type': 'intent', 'intent': intent})
            self.trace.append({'tool': '(verifier retry)', 'input': feedback, 'output': intent})
            still = [i for i in intent['items'] if not grounded(i, text)]
            if still:
                intent['items'] = [i for i in intent['items'] if i not in still]
                if intent['intent'] == 'deliver' and not intent['items']:
                    return (f'I am not sure what you want: I could not match any product in "{text}". The robot did '
                            'not move. Could you name the item, or say e.g. "charge" or "go to shelf 3"?')
        kind, items, dest = intent['intent'], intent['items'], intent['destination']
        stock = {sku: s['name'] for s in stations for sku in s.get('items', [])}

        if kind == 'cancel':
            return f'Cancel requested: {self._tool("cancel_mission").get("message", "ok")}'
        if kind == 'inventory':
            return '; '.join(f'{s["name"]}: {", ".join(s["items"])}' for s in stations if s.get('items'))
        status = self._tool('get_robot_status')
        if kind == 'status':
            return (f'{status.get("state")} near {status.get("nearest_station")}, battery {status.get("battery_pct")}%, '
                    f'carrying {status.get("carrying") or "nothing"}.')
        low = status.get('battery_pct', 100) < LOW_BATTERY
        if kind == 'charge':
            return self._report(self._tool('execute_mission', {'steps': [{'station': 'charging_dock', 'action': 'charge'}],
                                                               'mission_id': 'charge'}))
        pre = [{'station': 'charging_dock', 'action': 'charge'}] if low else []
        note = ' Charged first because the battery was low.' if low else ''
        if kind == 'goto':
            if not dest:
                return 'Where should the robot go? Stations: ' + ', '.join(s['name'] for s in stations)
            if dest == 'charging_dock':
                pre = []
            return self._report(self._tool('execute_mission', {'steps': pre + [{'station': dest, 'action': 'goto'}],
                                                               'mission_id': f'goto_{dest}'})) + note
        if kind == 'deliver':
            unknown = intent.get('unknown_items') or []
            if not items:
                what = ', '.join(unknown) if unknown else 'those items'
                return f'{what} is not stocked on any shelf, so the robot did not move.'
            dest = dest or 'packing_station'
            orders = [{'item': sku, 'pickup': stock[sku], 'dropoff': dest} for sku in items]
            if len(orders) == 1:
                steps = [{'station': orders[0]['pickup'], 'action': 'pick', 'item': orders[0]['item']},
                         {'station': dest, 'action': 'drop', 'item': orders[0]['item']}]
            else:
                plan = self._tool('plan_orders', {'orders': orders})
                if not plan.get('success'):
                    return f'Planning failed: {plan.get("message", plan.get("error"))}'
                steps = plan['steps']
            res = self._tool('execute_mission', {'steps': pre + steps, 'mission_id': 'delivery'})
            missing = f' (not stocked: {", ".join(unknown)})' if unknown else ''
            return self._report(res) + missing + note
        return ("I didn't understand that as a robot task. Try e.g. 'bring bolts to packing', "
                "'go to shelf 3', 'charge', or 'battery status'.")
