"""Shared helpers: API-key loading, agent construction, decision log."""
import json
import os
import time
from pathlib import Path

ENV_FILE = Path.home() / '.config' / 'amr_agent' / 'env'
LOG_DIR = Path.home() / '.ros' / 'amr_agent'


def load_env_file(path: Path = ENV_FILE) -> bool:
    """Load KEY=VALUE / export KEY=VALUE lines into os.environ (never printed). Returns True if a key is set."""
    if path.is_file():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, val = line.removeprefix('export ').split('=', 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
    return bool(os.environ.get('ANTHROPIC_API_KEY', '').strip())


def build_agent(backend, on_event=None, on_feedback=None, offline=False, model=None):
    """Return (agent, mode_description). Falls back to the rule agent when no key / SDK is available."""
    from amr_agent.rule_agent import RuleAgent
    from amr_agent.tools import ToolExecutor

    executor = ToolExecutor(backend, on_feedback=on_feedback)
    if not offline and load_env_file():
        try:
            from amr_agent.llm_agent import DEFAULT_MODEL, ClaudeAgent
            m = model or DEFAULT_MODEL
            return ClaudeAgent(executor, model=m, on_event=on_event), f'Claude ({m})'
        except ImportError:
            reason = 'anthropic SDK not installed (pip install anthropic)'
        except Exception as exc:  # bad key format etc.
            reason = f'{type(exc).__name__}: {exc}'
    else:
        reason = 'offline flag' if offline else f'no ANTHROPIC_API_KEY (looked in env and {ENV_FILE})'
    return RuleAgent(executor, on_event=on_event), f'rule-based fallback ({reason})'


class DecisionLog:
    """Append-only JSONL record of every request, tool call and reply, for review and evaluation."""

    def __init__(self, directory: Path = LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / 'decisions.jsonl'

    def write(self, mode, request, result):
        entry = {'ts': time.strftime('%Y-%m-%dT%H:%M:%S'), 'mode': mode, 'request': request, **result}
        with self.path.open('a') as f:
            f.write(json.dumps(entry, default=str) + '\n')
