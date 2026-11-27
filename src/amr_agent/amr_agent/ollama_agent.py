"""Tool-calling agent backed by a local open model served by Ollama (free, offline, on-device).

Same tools, safety layers and return format as ClaudeAgent. Uses Ollama's native /api/chat so the
context window can be set (the default is too small for the system prompt plus tool schemas).
No third-party dependencies: plain urllib.
"""
import json
import os
import time
import urllib.error
import urllib.request
from typing import Callable, List, Optional

from amr_agent.llm_agent import SYSTEM_PROMPT
from amr_agent.tools import TOOLS, ToolExecutor, to_json

OLLAMA_URL = os.environ.get('OLLAMA_HOST_URL', 'http://127.0.0.1:11434')
DEFAULT_OLLAMA_MODEL = os.environ.get('AMR_OLLAMA_MODEL', 'qwen2.5:3b')
# Ollama unloads an idle model after 5 min; reloading it under WSL took ~45 s. Keep it on the GPU.
KEEP_ALIVE = os.environ.get('AMR_OLLAMA_KEEP_ALIVE', '60m')


def warm_up(model: str = DEFAULT_OLLAMA_MODEL, url: str = OLLAMA_URL, background: bool = True):
    """Load the model onto the GPU now (an empty chat request), so the first real request is fast."""
    def _go():
        try:
            req = urllib.request.Request(f'{url}/api/chat', headers={'Content-Type': 'application/json'},
                                         data=json.dumps({'model': model, 'messages': [], 'keep_alive': KEEP_ALIVE}).encode())
            urllib.request.urlopen(req, timeout=300).read()
        except Exception:
            pass
    if background:
        import threading
        threading.Thread(target=_go, daemon=True).start()
    else:
        _go()

# Small models follow terse, explicit procedure better than prose.
SMALL_MODEL_ADDENDUM = """
Procedure (always follow it):
- To act, CALL a tool. Never write a tool call as text and never claim something was done without calling execute_mission.
- Items: call find_item for each item the person mentions; use the returned sku and station exactly.
- One item: execute_mission with [pick at its station, drop at the destination].
- Two or more items: plan_orders, then execute_mission with the returned steps unchanged.
- "go to X" / "send the robot to X": execute_mission with one goto step. "charge", "top up": one charge step at charging_dock.
- Questions only (battery, status, stock): answer from get_robot_status / list_stations; do not move the robot.
- Battery below 25% before a delivery: put {"station": "charging_dock", "action": "charge"} as the first step."""


def ollama_tools():
    return [{'type': 'function', 'function': {'name': t['name'], 'description': t['description'],
                                              'parameters': t['input_schema']}} for t in TOOLS]


def ollama_available(url: str = OLLAMA_URL, model: Optional[str] = None, timeout: float = 2.0) -> bool:
    """True if the server answers and (if given) the model has been pulled."""
    try:
        with urllib.request.urlopen(f'{url}/api/tags', timeout=timeout) as r:
            names = [m.get('name', '') for m in json.load(r).get('models', [])]
    except (urllib.error.URLError, OSError, ValueError):
        return False
    return model is None or model in names or f'{model}:latest' in names


class OllamaAgent:
    def __init__(self, executor: ToolExecutor, model: str = DEFAULT_OLLAMA_MODEL, url: str = OLLAMA_URL,
                 max_steps: int = 14, on_event: Optional[Callable[[dict], None]] = None, num_ctx: int = 8192,
                 max_history: int = 30, transport=None):
        self.executor, self.model, self.url = executor, model, url
        self.max_steps, self.num_ctx, self.max_history = max_steps, num_ctx, max_history
        self.on_event = on_event or (lambda e: None)
        self.transport = transport or self._post
        self.tools = ollama_tools()
        self.history: List[dict] = []

    def _post(self, payload: dict) -> dict:
        req = urllib.request.Request(f'{self.url}/api/chat', data=json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r)

    def _trim(self):
        if len(self.history) <= self.max_history:
            return
        for i in range(len(self.history) - self.max_history, len(self.history)):
            if self.history[i]['role'] == 'user':
                self.history = self.history[i:]
                return

    def ask(self, text: str) -> dict:
        t0, trace, reply = time.monotonic(), [], ''
        self.history.append({'role': 'user', 'content': text})
        self._trim()
        for _ in range(self.max_steps):
            payload = {'model': self.model, 'stream': False, 'tools': self.tools, 'keep_alive': KEEP_ALIVE,
                       'options': {'temperature': 0, 'num_ctx': self.num_ctx},
                       'messages': [{'role': 'system', 'content': SYSTEM_PROMPT + SMALL_MODEL_ADDENDUM}] + self.history}
            msg = self.transport(payload).get('message', {})
            calls = msg.get('tool_calls') or []
            self.history.append({'role': 'assistant', 'content': msg.get('content', '') or '',
                                 **({'tool_calls': calls} if calls else {})})
            if msg.get('content', '').strip():
                self.on_event({'type': 'thought', 'text': msg['content'].strip()})
            if not calls:
                reply = (msg.get('content') or '').strip()
                break
            for call in calls:
                fn = call.get('function', {})
                name, args = fn.get('name', ''), fn.get('arguments', {})
                if isinstance(args, str):  # some models return a JSON string
                    try:
                        args = json.loads(args or '{}')
                    except json.JSONDecodeError:
                        args = {'__invalid__': args}
                self.on_event({'type': 'tool_call', 'name': name, 'input': args})
                out = (self.executor.run(name, args) if '__invalid__' not in args
                       else {'error': 'arguments were not valid JSON'})
                self.on_event({'type': 'tool_result', 'name': name, 'output': out})
                trace.append({'tool': name, 'input': args, 'output': out})
                self.history.append({'role': 'tool', 'tool_name': name, 'content': to_json(out)})
        else:
            reply = 'I stopped after too many planning steps without finishing; please rephrase or simplify.'
        return {'reply': reply, 'trace': trace, 'steps': len(trace), 'seconds': round(time.monotonic() - t0, 1)}
