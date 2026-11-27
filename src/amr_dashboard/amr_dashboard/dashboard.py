"""Live operations dashboard for the warehouse AMR: http://localhost:8765

  - live map: SLAM map, stations, robot pose and heading, Nav2 global plan, recent trail
  - robot card: state, battery, cargo, current mission
  - command box: plain-English requests, published to /agent/command (needs agent_node)
  - event feed: agent intents, tool calls, mission progress, replies
  - KPIs from the agent decision log: missions, success rate, distance, mission time, agent latency,
    route-optimiser savings

Standard library HTTP server, no web framework. Binds to 127.0.0.1 only.
"""
import json
import math
import struct
import threading
import time
import zlib
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import rclpy
import yaml
from nav_msgs.msg import Path as NavPath
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String

from amr_dashboard.page import PAGE
from amr_interfaces.srv import ListStations

DECISION_LOG = Path.home() / '.ros' / 'amr_agent' / 'decisions.jsonl'


def pgm_to_png(pgm_path: Path) -> bytes:
    """Minimal PGM (P5, 8-bit) -> grayscale PNG encoder, so no imaging library is needed."""
    data = pgm_path.read_bytes()
    parts, idx = [], 0
    while len(parts) < 4:  # magic, width, height, maxval (skip comments)
        while data[idx:idx + 1].isspace():
            idx += 1
        if data[idx:idx + 1] == b'#':
            idx = data.index(b'\n', idx) + 1
            continue
        end = idx
        while not data[end:end + 1].isspace():
            end += 1
        parts.append(data[idx:end])
        idx = end
    w, h = int(parts[1]), int(parts[2])
    pixels = data[idx + 1: idx + 1 + w * h]
    raw = b''.join(b'\x00' + pixels[r * w:(r + 1) * w] for r in range(h))

    def chunk(tag, body):
        return struct.pack('>I', len(body)) + tag + body + struct.pack('>I', zlib.crc32(tag + body) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 0, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


def compute_kpis(log_path: Path = DECISION_LOG) -> dict:
    missions = ok = 0
    dist = dur = latency = planned = naive = 0.0
    n_lat = n_plan = 0
    if log_path.is_file():
        for line in log_path.read_text().splitlines()[-500:]:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            ex = [t['output'] for t in e.get('trace', []) if t.get('tool') == 'execute_mission'
                  and isinstance(t.get('output'), dict) and 'success' in t['output']]
            for o in ex:
                missions += 1
                ok += bool(o.get('success'))
                dist += float(o.get('distance_m', 0) or 0)
                dur += float(o.get('duration_s', 0) or 0)
            if ex:
                latency += max(0.0, float(e.get('seconds', 0)) - sum(float(o.get('duration_s', 0) or 0) for o in ex))
                n_lat += 1
            for t in e.get('trace', []):
                o = t.get('output')
                if t.get('tool') == 'plan_orders' and isinstance(o, dict) and o.get('naive_distance_m'):
                    planned += float(o['planned_distance_m'])
                    naive += float(o['naive_distance_m'])
                    n_plan += 1
    return {'missions': missions, 'success_rate': round(100 * ok / missions) if missions else None,
            'distance_m': round(dist, 1), 'avg_mission_s': round(dur / missions) if missions else None,
            'avg_agent_latency_s': round(latency / n_lat, 1) if n_lat else None,
            'route_saving_pct': round(100 * (1 - planned / naive)) if naive else None, 'plans': n_plan}


class Dashboard(Node):
    def __init__(self):
        super().__init__('amr_dashboard')
        self.declare_parameter('port', 8765)
        self.declare_parameter('map_yaml', str(Path.home() / 'warehouse_amr_ws/maps/warehouse_map_v4.yaml'))
        self.lock = threading.Lock()
        self.status, self.stations, self.plan = {}, [], []
        self.trail = deque(maxlen=400)
        self.events = deque(maxlen=80)
        self.kpis, self._kpi_t = {}, 0.0
        self._load_map(Path(self.get_parameter('map_yaml').value))
        self.cmd_pub = self.create_publisher(String, '/agent/command', 10)
        self.create_subscription(String, '/warehouse/status', self._on_status, 10)
        self.create_subscription(String, '/agent/events', self._on_event, 50)
        self.create_subscription(String, '/agent/response', self._on_response, 10)
        self.create_subscription(NavPath, '/plan', self._on_plan, 5)
        self._stations_client = self.create_client(ListStations, '/warehouse/list_stations')
        self.create_timer(2.0, self._fetch_stations)

    # ---- data ------------------------------------------------------------
    def _load_map(self, yaml_path: Path):
        meta = yaml.safe_load(yaml_path.read_text())
        img = (yaml_path.parent / meta['image']).resolve()
        self.map_png = pgm_to_png(img)
        head = self.map_png[16:24]
        w, h = struct.unpack('>II', head)
        self.map_meta = {'width': w, 'height': h, 'resolution': meta['resolution'],
                         'origin': meta['origin'][:2], 'name': yaml_path.stem}

    def _fetch_stations(self):
        if self.stations or not self._stations_client.service_is_ready():
            return
        fut = self._stations_client.call_async(ListStations.Request())
        fut.add_done_callback(lambda f: self._set_stations(f.result()))

    def _set_stations(self, res):
        with self.lock:
            self.stations = [{'name': s.name, 'type': s.type, 'x': s.x, 'y': s.y, 'items': list(s.items)}
                             for s in res.stations]

    def _event(self, kind, text):
        with self.lock:
            self.events.appendleft({'t': time.strftime('%H:%M:%S'), 'kind': kind, 'text': text})

    def _on_status(self, msg):
        st = json.loads(msg.data)
        with self.lock:
            prev = self.status
            self.status = st
            if st.get('x') is not None:
                if not self.trail or math.hypot(st['x'] - self.trail[-1][0], st['y'] - self.trail[-1][1]) > 0.05:
                    self.trail.append((round(st['x'], 2), round(st['y'], 2)))
        if prev.get('last_message') != st.get('last_message') and st.get('last_message'):
            self._event('robot', st['last_message'])

    def _on_event(self, msg):
        e = json.loads(msg.data)
        t = e.get('type')
        if t == 'intent':
            i = e['intent']
            self._event('intent', f'{i.get("intent")} {", ".join(i.get("items", []))} '
                                  f'{("→ " + i["destination"]) if i.get("destination") else ""}'.strip())
        elif t == 'verifier':
            self._event('verifier', f'corrected: {", ".join(e.get("rejected", []))}')
        elif t == 'tool_call' and e.get('name') in ('plan_orders', 'execute_mission', 'cancel_mission'):
            self._event('tool', e['name'])
        elif t == 'tool_result' and e.get('name') == 'plan_orders' and isinstance(e.get('output'), dict):
            self._event('plan', e['output'].get('message', ''))

    def _on_response(self, msg):
        r = json.loads(msg.data)
        self._event('reply', r.get('reply', ''))
        self._kpi_t = 0.0  # refresh KPIs

    def _on_plan(self, msg):
        pts = [(round(p.pose.position.x, 2), round(p.pose.position.y, 2)) for p in msg.poses[::3]]
        with self.lock:
            self.plan = pts

    def state(self):
        if time.monotonic() - self._kpi_t > 5.0:
            self.kpis, self._kpi_t = compute_kpis(), time.monotonic()
        with self.lock:
            return {'status': self.status, 'stations': self.stations, 'plan': self.plan,
                    'trail': list(self.trail)[-200:], 'events': list(self.events)[:40], 'kpis': self.kpis,
                    'map': self.map_meta, 'server_time': time.strftime('%H:%M:%S')}

    def command(self, text):
        text = text.strip()[:300]
        if text:
            self.cmd_pub.publish(String(data=text))
            self._event('you', text)
        return bool(text)


def make_handler(dash: Dashboard):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ('/', '/index.html'):
                self._send(200, PAGE.encode(), 'text/html; charset=utf-8')
            elif self.path.startswith('/api/state'):
                self._send(200, json.dumps(dash.state()).encode(), 'application/json')
            elif self.path.startswith('/map.png'):
                self._send(200, dash.map_png, 'image/png')
            else:
                self._send(404, b'not found', 'text/plain')

        def do_POST(self):
            if self.path != '/api/command':
                return self._send(404, b'not found', 'text/plain')
            n = min(int(self.headers.get('Content-Length', 0)), 4096)
            try:
                text = json.loads(self.rfile.read(n) or b'{}').get('text', '')
            except json.JSONDecodeError:
                return self._send(400, b'bad json', 'text/plain')
            self._send(200, json.dumps({'accepted': dash.command(text)}).encode(), 'application/json')
    return Handler


def main():
    rclpy.init()
    node = Dashboard()
    node.set_parameters([rclpy.parameter.Parameter('use_sim_time', value=True)])
    port = int(node.get_parameter('port').value)
    server = ThreadingHTTPServer(('127.0.0.1', port), make_handler(node))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    node.get_logger().info(f'AMR dashboard on http://localhost:{port}')
    ex = MultiThreadedExecutor(num_threads=3)
    ex.add_node(node)
    try:
        ex.spin()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
