#!/usr/bin/env python3
"""Drive a SLAM mapping lap through the warehouse aisles (run with warehouse_simulation + amr_slam up).

    python3 scripts/mapping_drive.py                      # default lap for the racked warehouse
    python3 scripts/mapping_drive.py '[[3.8,0],[0,0]]'    # custom waypoints (map frame)

Steers on the SLAM-corrected pose (map -> base_footprint TF), falling back to /odom until SLAM publishes,
and stops if the LiDAR sees anything closer than 0.45 m in front.
"""
import json
import math
import sys
import time

import rclpy
from geometry_msgs.msg import TwistStamped
from nav_msgs.msg import Odometry
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from tf2_ros import Buffer, TransformListener

# aisle B -> east zone -> aisle A -> cross aisle -> west passage -> south area -> back to spawn
DEFAULT_LAP = [(3.8, 0.0), (3.8, 2.6), (-0.8, 2.6), (-5.2, 2.6), (-5.2, 0.0), (-5.2, -3.4),
               (-0.8, -3.4), (-0.8, 0.0), (-0.8, -3.4), (3.8, -3.4), (3.8, 0.0), (0.0, 0.0)]
V_MAX, W_MAX, POS_TOL, STOP_DIST = 0.35, 0.8, 0.15, 0.45


def yaw_of(q):
    return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))


class Driver(Node):
    def __init__(self, waypoints):
        super().__init__('mapping_drive')
        self.set_parameters([rclpy.parameter.Parameter('use_sim_time', value=True)])
        self.wps, self.idx, self.done = waypoints, 0, False
        self.pub = self.create_publisher(TwistStamped, '/cmd_vel', 10)
        self.odom_pose, self.front_min, self.blocked_since = None, float('inf'), None
        self.create_subscription(Odometry, '/odom', self.on_odom, 10)
        self.create_subscription(LaserScan, '/scan', self.on_scan, 10)
        self.tf_buf = Buffer()
        self.tf_l = TransformListener(self.tf_buf, self)
        self.create_timer(0.05, self.step)

    def on_odom(self, m):
        p = m.pose.pose
        self.odom_pose = (p.position.x, p.position.y, yaw_of(p.orientation))

    def on_scan(self, s):
        best = float('inf')
        for i, r in enumerate(s.ranges):
            a = math.atan2(math.sin(s.angle_min + i * s.angle_increment), math.cos(s.angle_min + i * s.angle_increment))
            if abs(a) < math.radians(35) and s.range_min < r < s.range_max:
                best = min(best, r)
        self.front_min = best

    def pose(self):
        try:
            t = self.tf_buf.lookup_transform('map', 'base_footprint', rclpy.time.Time())
            return t.transform.translation.x, t.transform.translation.y, yaw_of(t.transform.rotation)
        except Exception:
            return self.odom_pose

    def send(self, v, w):
        m = TwistStamped()
        m.header.stamp, m.header.frame_id = self.get_clock().now().to_msg(), 'base_footprint'
        m.twist.linear.x, m.twist.angular.z = v, w
        self.pub.publish(m)

    def step(self):
        p = self.pose()
        if p is None or self.done:
            return
        if self.idx >= len(self.wps):
            self.send(0.0, 0.0)
            self.done = True
            return
        x, y, yaw = p
        gx, gy = self.wps[self.idx]
        dist = math.hypot(gx - x, gy - y)
        if dist < POS_TOL:
            print(f'reached wp{self.idx} ({gx}, {gy})  pose=({x:.2f}, {y:.2f})', flush=True)
            self.idx += 1
            return
        err = math.atan2(math.sin(math.atan2(gy - y, gx - x) - yaw), math.cos(math.atan2(gy - y, gx - x) - yaw))
        w = max(-W_MAX, min(W_MAX, 1.8 * err))
        v = 0.0 if abs(err) > 0.35 else min(V_MAX, 0.6 * dist) * math.cos(err)
        if v > 0 and self.front_min < STOP_DIST:
            if self.blocked_since is None:
                self.blocked_since = time.time()
                print(f'SAFETY STOP: obstacle {self.front_min:.2f} m ahead', flush=True)
            v = 0.0
            if time.time() - self.blocked_since > 10:
                print('blocked for 10 s, aborting', flush=True)
                self.done = True
        else:
            self.blocked_since = None
        self.send(v, w)


def main():
    wps = [tuple(p) for p in json.loads(sys.argv[1])] if len(sys.argv) > 1 else DEFAULT_LAP
    rclpy.init()
    n = Driver(wps)
    t0 = time.time()
    try:
        while rclpy.ok() and not n.done and time.time() - t0 < 800:
            rclpy.spin_once(n, timeout_sec=0.1)
    finally:
        for _ in range(5):
            n.send(0.0, 0.0)
            time.sleep(0.05)
        print(f'finished {n.idx}/{len(wps)} waypoints in {time.time() - t0:.0f} s', flush=True)
        n.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
