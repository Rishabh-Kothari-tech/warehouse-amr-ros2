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


_CLAUDE_PROBE = {}


def claude_usable(model):
    """One tiny request, cached per process: a key alone is not enough (e.g. no API credits)."""
    if model in _CLAUDE_PROBE:
        return _CLAUDE_PROBE[model]
    if not load_env_file():
        _CLAUDE_PROBE[model] = (False, f'no ANTHROPIC_API_KEY (looked in env and {ENV_FILE})')
        return _CLAUDE_PROBE[model]
    try:
        import anthropic
        anthropic.Anthropic().messages.create(model=model, max_tokens=4,
                                              messages=[{'role': 'user', 'content': 'ok'}])
        _CLAUDE_PROBE[model] = (True, '')
    except ImportError:
        _CLAUDE_PROBE[model] = (False, 'anthropic SDK not installed (pip install anthropic)')
    except Exception as exc:  # auth, credits, network, unknown model
        _CLAUDE_PROBE[model] = (False, f'Claude API unavailable: {type(exc).__name__}: {str(exc)[:160]}')
    return _CLAUDE_PROBE[model]


def build_agent(backend, on_event=None, on_feedback=None, offline=False, model=None, kind=None):
    """Return (agent, mode_description).

    kind (or $AMR_AGENT_BACKEND):
      'claude'  Claude tool-use loop
      'local'   hybrid: local Ollama model parses intent (constrained JSON), code plans and executes
      'ollama'  local Ollama model running the free-form tool-use loop (weak for small models)
      'rule'    keyword parser, no model
      'auto'    (default) Claude if a test call succeeds, else 'local' if Ollama is up, else 'rule'.
    """
    from amr_agent.rule_agent import RuleAgent
    from amr_agent.tools import ToolExecutor

    executor = ToolExecutor(backend, on_feedback=on_feedback)
    load_env_file()
    kind = 'rule' if offline else (kind or os.environ.get('AMR_AGENT_BACKEND', 'auto')).lower()
    reasons = []
    if kind in ('auto', 'claude'):
        from amr_agent.llm_agent import DEFAULT_MODEL, ClaudeAgent
        m = model if (model and kind == 'claude') else DEFAULT_MODEL
        ok, why = claude_usable(m)
        if ok:
            return ClaudeAgent(executor, model=m, on_event=on_event), f'Claude ({m})'
        reasons.append(why)
    if kind in ('auto', 'local', 'ollama'):
        from amr_agent.ollama_agent import DEFAULT_OLLAMA_MODEL, OllamaAgent, ollama_available
        m = model if (model and kind != 'auto') else DEFAULT_OLLAMA_MODEL
        if ollama_available(model=m):
            if kind == 'ollama':
                return OllamaAgent(executor, model=m, on_event=on_event), f'local tool-use loop via Ollama ({m})'
            from amr_agent.intent_agent import LocalIntentAgent
            return LocalIntentAgent(executor, model=m, on_event=on_event), f'local hybrid intent agent via Ollama ({m})'
        reasons.append(f'Ollama not running or model {m} not pulled (ollama pull {m})')
    if kind == 'rule':
        reasons.append('rule-based requested')
    return RuleAgent(executor, on_event=on_event), f'rule-based fallback ({"; ".join(reasons)})'


class DecisionLog:
    """Append-only JSONL record of every request, tool call and reply, for review and evaluation."""

    def __init__(self, directory: Path = LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / 'decisions.jsonl'

    def write(self, mode, request, result):
        entry = {'ts': time.strftime('%Y-%m-%dT%H:%M:%S'), 'mode': mode, 'request': request, **result}
        with self.path.open('a') as f:
            f.write(json.dumps(entry, default=str) + '\n')
