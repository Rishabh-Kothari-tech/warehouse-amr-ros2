"""ROS 2 front-end for the agent, so other systems (a dashboard, a voice front-end, a WMS bridge)
can send plain-language requests over topics.

  sub  /agent/command   std_msgs/String  "bring two bearings to packing"
  pub  /agent/response  std_msgs/String  JSON {request, reply, steps, seconds, mode}
  pub  /agent/events    std_msgs/String  JSON per tool call / result / mission feedback

Requests are queued and handled one at a time.
"""
import json
import queue
import threading

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from amr_agent.common import DecisionLog, build_agent
from amr_agent.ros_client import WarehouseClient


class AgentNode(Node):
    def __init__(self):
        super().__init__('amr_agent')
        self.declare_parameter('offline', False)
        self.declare_parameter('model', '')
        self.resp_pub = self.create_publisher(String, '/agent/response', 10)
        self.event_pub = self.create_publisher(String, '/agent/events', 50)
        self.backend = WarehouseClient('amr_agent_backend')
        self.agent, self.mode = build_agent(
            self.backend, on_event=self._event, on_feedback=lambda f: self._event({'type': 'feedback', **f}),
            offline=self.get_parameter('offline').value, model=self.get_parameter('model').value or None)
        self.log = DecisionLog()
        self.queue: 'queue.Queue[str]' = queue.Queue()
        self.create_subscription(String, '/agent/command', lambda m: self.queue.put(m.data), 10)
        threading.Thread(target=self._worker, daemon=True).start()
        self.get_logger().info(f'Agent ready ({self.mode}); send requests on /agent/command')

    def _event(self, e):
        self.event_pub.publish(String(data=json.dumps(e, default=str)))

    def _worker(self):
        while rclpy.ok():
            text = self.queue.get()
            self.get_logger().info(f'request: {text}')
            result = self.agent.ask(text)
            self.log.write(self.mode, text, result)
            out = {'request': text, 'reply': result['reply'], 'steps': result['steps'],
                   'seconds': result['seconds'], 'mode': self.mode}
            self.resp_pub.publish(String(data=json.dumps(out)))
            self.get_logger().info(f'reply: {result["reply"]}')


def main():
    rclpy.init()
    node = AgentNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
