"""Deterministic fallback agent: keyword parsing, no LLM. Used when no API key is configured,
and as a baseline to compare the LLM agent against. Handles the common command shapes:
  status / where are you / battery          -> status report
  list stations / inventory                 -> station list
  charge / go charge                        -> drive to charging_dock and charge
  go to shelf 3 / go home                   -> goto
  bring bolts and bearings (to packing)     -> find SKUs, optimise, pick + drop
  stop / cancel                             -> cancel
"""
import re
import time

from amr_agent.tools import ToolExecutor

STATION_ALIASES = [
    (r'\bshelf[\s_-]*1\b|\bshelf one\b', 'shelf_1'), (r'\bshelf[\s_-]*2\b|\bshelf two\b', 'shelf_2'),
    (r'\bshelf[\s_-]*3\b|\bshelf three\b', 'shelf_3'), (r'\bshelf[\s_-]*4\b|\bshelf four\b', 'shelf_4'),
    (r'\bpack(ing)?\b', 'packing_station'), (r'\bcharg(e|er|ing)\b|\bdock\b', 'charging_dock'),
    (r'\bhome\b|\bstart\b', 'home'),
]
LOW_BATTERY = 25.0


def match_station(text):
    for pattern, name in STATION_ALIASES:
        if re.search(pattern, text):
            return name
    return None


class RuleAgent:
    def __init__(self, executor: ToolExecutor, on_event=None):
        self.executor, self.on_event = executor, on_event or (lambda e: None)
        self.trace = []

    def _tool(self, name, args=None):
        self.on_event({'type': 'tool_call', 'name': name, 'input': args or {}})
        out = self.executor.run(name, args or {})
        self.on_event({'type': 'tool_result', 'name': name, 'output': out})
        self.trace.append({'tool': name, 'input': args or {}, 'output': out})
        return out

    @staticmethod
    def _report(res):
        if 'error' in res:
            return f'Could not run that: {res["error"]}'
        if not res.get('success'):
            return f'Mission failed: {res.get("message")}'
        return (f'Done: {res.get("message")}. Drove {res.get("distance_m", 0):.1f} m in '
                f'{res.get("duration_s", 0):.0f} s; battery now {res.get("battery_pct", 0):.0f}%.')

    def ask(self, text: str) -> dict:
        t0, self.trace = time.monotonic(), []
        reply = self._handle(text.lower().strip())
        return {'reply': reply, 'trace': self.trace, 'steps': len(self.trace), 'seconds': round(time.monotonic() - t0, 1)}

    def _handle(self, t):
        if re.search(r'\b(stop|cancel|abort)\b', t):
            return f'Cancel requested: {self._tool("cancel_mission").get("message", "ok")}'
        if re.search(r'\b(status|battery|where are you|state)\b', t):
            s = self._tool('get_robot_status')
            return (f'{s.get("state")} near {s.get("nearest_station")}, battery {s.get("battery_pct")}%, '
                    f'carrying {s.get("carrying") or "nothing"}.')
        if re.search(r'\b(list|stations|inventory|what.*stock)\b', t):
            st = self._tool('list_stations')['stations']
            return '; '.join(f'{s["name"]}' + (f' ({", ".join(s["items"])})' if s.get('items') else '') for s in st)

        status = self._tool('get_robot_status')
        pre = []
        if status.get('battery_pct', 100) < LOW_BATTERY and not re.search(r'\bcharg', t):
            pre = [{'station': 'charging_dock', 'action': 'charge'}]

        if re.search(r'\bcharg(e|ing)\b', t) and not re.search(r'\b(bring|fetch|get|deliver|pick)\b', t):
            return self._report(self._tool('execute_mission', {'steps': [{'station': 'charging_dock', 'action': 'charge'}],
                                                               'mission_id': 'charge'}))

        m = re.search(r'\b(bring|fetch|get|deliver|pick up|pick)\b(.*)', t)
        if m:
            body = m.group(2)
            dest = 'packing_station'
            dm = re.search(r'\b(?:to|at)\s+(?:the\s+)?(.+)$', body)
            if dm and match_station(dm.group(1)):
                dest, body = match_station(dm.group(1)), body[:dm.start()]
            phrases = [p.strip() for p in re.split(r',|\band\b|&', re.sub(r'\b(me|some|a|an|the|box(es)? of|two|one)\b', ' ', body))
                       if p.strip()]
            orders, missing = [], []
            for p in phrases:
                found = self._tool('find_item', {'query': p})['matches']
                if found:
                    orders.append({'item': found[0]['sku'], 'pickup': found[0]['station'], 'dropoff': dest})
                else:
                    missing.append(p)
            if missing and not orders:
                return f'I could not find {", ".join(missing)} on any shelf.'
            if len(orders) == 1:
                steps = [{'station': orders[0]['pickup'], 'action': 'pick', 'item': orders[0]['item']},
                         {'station': dest, 'action': 'drop', 'item': orders[0]['item']}]
            else:
                plan = self._tool('plan_orders', {'orders': orders})
                if not plan.get('success'):
                    return f'Planning failed: {plan.get("message", plan.get("error"))}'
                steps = plan['steps']
            res = self._tool('execute_mission', {'steps': pre + steps, 'mission_id': 'delivery'})
            note = f' (not found: {", ".join(missing)})' if missing else ''
            charged = ' Charged first because the battery was low.' if pre else ''
            return self._report(res) + note + charged

        if re.search(r'\b(go|drive|move|return|head)\b', t):
            st = match_station(t)
            if st:
                return self._report(self._tool('execute_mission', {'steps': pre + [{'station': st, 'action': 'goto'}],
                                                                   'mission_id': f'goto_{st}'}))
        return ("Offline mode understands: status, list stations, charge, go to <station>, "
                "bring <item> [and <item>] [to <station>], cancel.")
