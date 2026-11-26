
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist


class AMRVelocityController(Node):

    def __init__(self):
        super().__init__('amr_velocity_controller')

        self.publisher_ = self.create_publisher(
            Twist,
            '/cmd_vel',
            10
        )

        self.timer = self.create_timer(
            0.1,
            self.publish_velocity
        )

        self.get_logger().info('AMR Velocity Controller Started')
        self.get_logger().info('Publishing forward velocity: 0.2 m/s')

    def publish_velocity(self):
        msg = Twist()

        msg.linear.x = 0.2
        msg.angular.z = 0.0

        self.publisher_.publish(msg)


def main(args=None):
    rclpy.init(args=args)

    node = AMRVelocityController()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        # Publish a stop command before shutting down
        stop_msg = Twist()
        node.publisher_.publish(stop_msg)

        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
