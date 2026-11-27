"""Synchronous ROS 2 client for the warehouse manager, used as the agent's tool backend.

Spins its own node on a background MultiThreadedExecutor so tool calls can block.
"""
import math
import threading
import time

import rclpy
from rclpy.action import ActionClient
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from amr_interfaces.action import ExecuteMission
from amr_interfaces.msg import MissionStep, Order
from amr_interfaces.srv import GetRobotStatus, ListStations, PlanOrders


class WarehouseClient:
    def __init__(self, node_name='amr_agent_client'):
        if not rclpy.ok():
            rclpy.init()
        self.node = Node(node_name)
        self.node.set_parameters([rclpy.parameter.Parameter('use_sim_time', value=True)])
        self._list = self.node.create_client(ListStations, '/warehouse/list_stations')
        self._status = self.node.create_client(GetRobotStatus, '/warehouse/get_status')
        self._plan = self.node.create_client(PlanOrders, '/warehouse/plan_orders')
        self._mission = ActionClient(self.node, ExecuteMission, '/warehouse/execute_mission')
        self._goal_handle = None
        self._executor = MultiThreadedExecutor(num_threads=2)
        self._executor.add_node(self.node)
        threading.Thread(target=self._executor.spin, daemon=True).start()

    @staticmethod
    def _wait(future, timeout):
        end = time.monotonic() + timeout
        while not future.done():
            if time.monotonic() > end:
                raise TimeoutError('warehouse manager did not answer in time')
            time.sleep(0.02)
        return future.result()

    def _call(self, client, req, timeout=10.0):
        if not client.wait_for_service(timeout_sec=5.0):
            raise RuntimeError(f'service {client.srv_name} not available (is warehouse_manager running?)')
        return self._wait(client.call_async(req), timeout)

    def list_stations(self):
        res = self._call(self._list, ListStations.Request())
        return [{'name': s.name, 'type': s.type, 'x': round(s.x, 2), 'y': round(s.y, 2),
                 'yaw_deg': round(math.degrees(s.yaw)), 'items': list(s.items)} for s in res.stations]

    def get_status(self):
        r = self._call(self._status, GetRobotStatus.Request())
        return {'x': round(r.x, 2), 'y': round(r.y, 2), 'yaw_deg': round(math.degrees(r.yaw)),
                'battery_pct': round(r.battery_pct, 1), 'state': r.state, 'nearest_station': r.nearest_station,
                'current_mission': r.current_mission, 'carrying': list(r.carrying), 'capacity': r.capacity,
                'odometer_m': round(r.odometer_m, 1), 'last_message': r.last_message}

    def plan_orders(self, orders, start_station='', end_station=''):
        req = PlanOrders.Request()
        req.orders = [Order(order_id=o.get('order_id', ''), item=o['item'], pickup=o['pickup'], dropoff=o['dropoff'])
                      for o in orders]
        req.start_station, req.end_station = start_station, end_station
        r = self._call(self._plan, req, timeout=120.0)
        return {'success': r.success, 'message': r.message,
                'steps': [{'station': s.station, 'action': s.action, 'item': s.item} for s in r.steps],
                'planned_distance_m': round(r.planned_distance_m, 2), 'naive_distance_m': round(r.naive_distance_m, 2)}

    def execute_mission(self, steps, mission_id='', on_feedback=None, timeout=900.0):
        if not self._mission.wait_for_server(timeout_sec=5.0):
            raise RuntimeError('execute_mission action not available (is warehouse_manager running?)')
        goal = ExecuteMission.Goal()
        goal.mission_id = mission_id
        goal.steps = [MissionStep(station=s['station'], action=s['action'], item=s.get('item', '')) for s in steps]

        def fb(msg):
            if on_feedback:
                f = msg.feedback
                on_feedback({'step': f.step_index, 'of': f.total_steps, 'station': f.station, 'action': f.action,
                             'state': f.state, 'battery_pct': round(f.battery_pct, 1)})

        gh = self._wait(self._mission.send_goal_async(goal, feedback_callback=fb), 15.0)
        if not gh.accepted:
            return {'success': False, 'message': 'mission rejected: robot is busy with another mission'}
        self._goal_handle = gh
        try:
            r = self._wait(gh.get_result_async(), timeout).result
        except KeyboardInterrupt:
            self.cancel_mission()
            return {'success': False, 'message': 'mission canceled by operator (Ctrl+C)'}
        finally:
            self._goal_handle = None
        return {'success': r.success, 'message': r.message, 'steps_completed': r.steps_completed,
                'steps_total': len(steps), 'distance_m': round(r.distance_m, 2), 'duration_s': round(r.duration_s, 1),
                'battery_pct': round(r.battery_pct, 1)}

    def cancel_mission(self):
        gh = self._goal_handle
        if gh is None:
            return {'success': True, 'message': 'no mission running from this client'}
        self._wait(gh.cancel_goal_async(), 10.0)
        return {'success': True, 'message': 'cancel sent'}

    def shutdown(self):
        self._executor.shutdown()
        self.node.destroy_node()
        rclpy.try_shutdown()
