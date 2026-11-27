"""Chat with the warehouse robot in plain English.

    ros2 run amr_agent chat                         # interactive
    ros2 run amr_agent chat --once "bring me bolts and a BMS board"
    ros2 run amr_agent chat --offline               # rule-based, no LLM
    ros2 run amr_agent chat --backend local         # local open model (hybrid intent agent)

Ctrl+C while a mission runs cancels the mission; Ctrl+C at the prompt exits.
"""
import argparse
import json
import sys

from amr_agent.common import DecisionLog, build_agent


def _short(obj, n=160):
    s = json.dumps(obj, default=str)
    return s if len(s) <= n else s[:n - 3] + '...'


def main(argv=None):
    ap = argparse.ArgumentParser(description='Natural-language interface to the warehouse AMR')
    ap.add_argument('--once', action='append', help='run this request and exit (repeatable)')
    ap.add_argument('--offline', action='store_true', help='use the rule-based agent, no LLM')
    ap.add_argument('--backend', choices=['auto', 'claude', 'local', 'ollama', 'rule'],
                    help='agent backend (default: $AMR_AGENT_BACKEND or auto)')
    ap.add_argument('--model', help='model id for the chosen backend')
    ap.add_argument('--quiet', action='store_true', help='hide tool calls')
    args, _ = ap.parse_known_args(argv)

    from amr_agent.ros_client import WarehouseClient

    def on_event(e):
        if args.quiet:
            return
        if e['type'] == 'tool_call':
            print(f'  -> {e["name"]}({_short(e["input"], 140)})', flush=True)
        elif e['type'] == 'intent':
            print(f'  intent: {json.dumps(e["intent"])}', flush=True)
        elif e['type'] == 'verifier':
            print(f'  verifier: rejected ungrounded items {e["rejected"]}, asking the model again', flush=True)
        elif e['type'] == 'tool_result':
            print(f'  <- {_short(e["output"])}', flush=True)

    def on_feedback(f):
        if not args.quiet:
            print(f'     [{f["step"]}/{f["of"]}] {f["state"]:<10} {f["action"]:<6} @ {f["station"]:<16} '
                  f'battery {f["battery_pct"]:.0f}%', flush=True)

    backend = WarehouseClient()
    agent, mode = build_agent(backend, on_event=on_event, on_feedback=on_feedback, offline=args.offline,
                              model=args.model, kind=args.backend)
    log = DecisionLog()
    print(f'Warehouse AMR agent - {mode}. Decision log: {log.path}', flush=True)

    def handle(text):
        print(f'\n> {text}', flush=True)
        result = agent.ask(text)
        print(f'\nAMR: {result["reply"]}\n    ({result["steps"]} tool calls, {result["seconds"]} s)', flush=True)
        log.write(mode, text, result)

    try:
        if args.once:
            for text in args.once:
                handle(text)
            return 0
        while True:
            try:
                text = input('\nyou> ').strip()
            except EOFError:
                break
            if text.lower() in ('exit', 'quit'):
                break
            if text:
                handle(text)
    except KeyboardInterrupt:
        print('\nbye')
    finally:
        backend.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
