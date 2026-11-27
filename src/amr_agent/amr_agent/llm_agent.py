"""Claude tool-use agent that turns natural-language warehouse requests into robot missions."""
import os
import time
from typing import Callable, List, Optional

from amr_agent.tools import TOOLS, ToolExecutor, to_json

DEFAULT_MODEL = os.environ.get('AMR_AGENT_MODEL', 'claude-sonnet-5-5')

SYSTEM_PROMPT = """You are the mission planner for an autonomous mobile robot (AMR) in a small warehouse.
You control the robot ONLY through the provided tools. Speak to warehouse staff: brief, concrete, no jargon.

Warehouse facts:
- Stations: shelves (shelf_1..shelf_4, each stocks specific SKUs), packing_station, charging_dock, home.
- The robot carries at most `capacity` items (see get_robot_status). Picking and dropping take a few seconds each.
- The battery drains about 1.5% per metre driven. Charging only happens at charging_dock (action "charge").

How to work:
1. Start every new request with get_robot_status. Use find_item to turn what people ask for into exact SKUs and
   stations; never invent SKU or station names. If an item is not stocked anywhere, say so and do not move.
2. Deliveries go to packing_station unless the person names another destination.
3. For two or more items, call plan_orders and execute its steps exactly (it minimises distance and handles
   capacity). For a single item, a pick step then a drop step is fine.
4. Battery safety: estimate the trip length (plan_orders reports it; otherwise ~4 m per station visited). If the
   battery would end below 20%, charge first (or immediately if already below 25%) and tell the person why.
5. If the request is ambiguous in a way that changes what the robot does (e.g. two different SKUs match), ask ONE
   short question instead of guessing. Otherwise act without asking for confirmation.
6. If a tool returns an error or a mission fails, explain it plainly and propose the next step. Do not retry the
   same failing mission more than once.
7. After a mission, report: what was done, distance driven, time taken and remaining battery."""


class ClaudeAgent:
    """Multi-turn tool-calling loop. `client` is an anthropic.Anthropic (or a test double)."""

    def __init__(self, executor: ToolExecutor, client=None, model: str = DEFAULT_MODEL, max_steps: int = 16,
                 on_event: Optional[Callable[[dict], None]] = None, max_history: int = 40):
        if client is None:
            import anthropic  # imported lazily so the package works without the SDK installed
            client = anthropic.Anthropic()
        self.client, self.executor, self.model = client, executor, model
        self.max_steps, self.on_event, self.max_history = max_steps, on_event or (lambda e: None), max_history
        self.messages: List[dict] = []

    def _trim_history(self):
        if len(self.messages) <= self.max_history:
            return
        # cut only at a plain user text turn, so tool_use/tool_result pairs are never split
        for i in range(len(self.messages) - self.max_history, len(self.messages)):
            m = self.messages[i]
            if m['role'] == 'user' and isinstance(m['content'], str):
                self.messages = self.messages[i:]
                return

    def ask(self, text: str) -> dict:
        """Run one user request to completion. Returns {'reply', 'trace', 'steps', 'seconds'}."""
        t0, trace = time.monotonic(), []
        self.messages.append({'role': 'user', 'content': text})
        self._trim_history()
        reply = ''
        for _ in range(self.max_steps):
            resp = self.client.messages.create(model=self.model, max_tokens=2048, system=SYSTEM_PROMPT,
                                               tools=TOOLS, messages=self.messages)
            self.messages.append({'role': 'assistant', 'content': resp.content})
            texts = [b.text for b in resp.content if getattr(b, 'type', '') == 'text' and b.text.strip()]
            for t in texts:
                self.on_event({'type': 'thought', 'text': t})
            if resp.stop_reason != 'tool_use':
                reply = '\n'.join(texts).strip()
                break
            results = []
            for block in resp.content:
                if getattr(block, 'type', '') != 'tool_use':
                    continue
                self.on_event({'type': 'tool_call', 'name': block.name, 'input': block.input})
                out = self.executor.run(block.name, block.input)
                self.on_event({'type': 'tool_result', 'name': block.name, 'output': out})
                trace.append({'tool': block.name, 'input': block.input, 'output': out})
                results.append({'type': 'tool_result', 'tool_use_id': block.id, 'content': to_json(out),
                                'is_error': isinstance(out, dict) and 'error' in out})
            self.messages.append({'role': 'user', 'content': results})
        else:
            reply = 'I stopped after too many planning steps without finishing; please rephrase or simplify.'
        return {'reply': reply, 'trace': trace, 'steps': len(trace), 'seconds': round(time.monotonic() - t0, 1)}
