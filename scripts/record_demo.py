#!/usr/bin/env python3
"""Record one agent mission for the demo GIF: sends a request to /agent/command and logs robot status,
the Nav2 plan and agent events until the agent replies.

    python3 scripts/record_demo.py "I need bolts and bearings at packing" demo.jsonl

Needs the full stack running (simulation, navigation, warehouse_tasks, amr_dashboard ops.launch.py).
Render with scripts/render_demo_gif.py.
"""
import json
import sys
import time

import rclpy
from nav_msgs.msg import Path
from rclpy.node import Node
from std_msgs.msg import String

from amr_interfaces.srv import ListStations


def main():
    request, out = sys.argv[1], sys.argv[2]
    rclpy.init()
    n = Node('demo_recorder')
    n.set_parameters([rclpy.parameter.Parameter('use_sim_time', value=True)])
    t0, rows, done = time.time(), [], {'reply': None}

    def log(kind, data):
        rows.append({'t': round(time.time() - t0, 2), 'kind': kind, 'data': data})

    n.create_subscription(String, '/warehouse/status', lambda m: log('status', json.loads(m.data)), 10)
    n.create_subscription(String, '/agent/events', lambda m: log('event', json.loads(m.data)), 50)
    n.create_subscription(Path, '/plan', lambda m: log('plan', [(round(p.pose.position.x, 2), round(p.pose.position.y, 2))
                                                              for p in m.poses[::4]]), 5)

    def on_resp(m):
        done['reply'] = json.loads(m.data)
        log('reply', done['reply'])
    n.create_subscription(String, '/agent/response', on_resp, 10)

    cli = n.create_client(ListStations, '/warehouse/list_stations')
    cli.wait_for_service(timeout_sec=10)
    fut = cli.call_async(ListStations.Request())
    rclpy.spin_until_future_complete(n, fut, timeout_sec=10)
    stations = [{'name': s.name, 'type': s.type, 'x': s.x, 'y': s.y} for s in fut.result().stations]

    pub = n.create_publisher(String, '/agent/command', 10)
    for _ in range(20):  # let the subscriptions match before publishing
        rclpy.spin_once(n, timeout_sec=0.1)
    log('request', request)
    pub.publish(String(data=request))
    while done['reply'] is None and time.time() - t0 < 300:
        rclpy.spin_once(n, timeout_sec=0.05)
    end = time.time() + 2
    while time.time() < end:
        rclpy.spin_once(n, timeout_sec=0.05)
    with open(out, 'w') as f:
        f.write(json.dumps({'kind': 'meta', 'stations': stations, 'request': request}) + '\n')
        for r in rows:
            f.write(json.dumps(r) + '\n')
    print(f'recorded {len(rows)} messages over {time.time() - t0:.0f} s -> {out}')
    print('reply:', (done['reply'] or {}).get('reply'))
    n.destroy_node()
    rclpy.try_shutdown()


if __name__ == '__main__':
    main()
