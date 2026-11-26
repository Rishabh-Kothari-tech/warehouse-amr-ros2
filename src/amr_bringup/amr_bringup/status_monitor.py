
import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class AMRStatusMonitor(Node):

    def __init__(self):
        super().__init__('amr_status_monitor')

        self.subscription = self.create_subscription(
            String,
            '/amr/status',
            self.status_callback,
            10
        )

        self.get_logger().info('AMR Status Monitor Started')

    def status_callback(self, msg):
        self.get_logger().info(f'Received: {msg.data}')


def main(args=None):
    rclpy.init(args=args)

    node = AMRStatusMonitor()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass

    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
