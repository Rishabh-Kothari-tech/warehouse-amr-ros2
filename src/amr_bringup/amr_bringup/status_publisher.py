
import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class AMRStatusPublisher(Node):

    def __init__(self):
        super().__init__('amr_status_publisher')

        # Create a publisher for the AMR status
        self.publisher_ = self.create_publisher(
            String,
            '/amr/status',
            10
        )

        # Publish status every 1 second
        self.timer = self.create_timer(
            1.0,
            self.publish_status
        )

        self.get_logger().info('AMR Status Publisher Started')

    def publish_status(self):
        msg = String()
        msg.data = 'AMR Status: IDLE'

        self.publisher_.publish(msg)

        self.get_logger().info(f'Publishing: {msg.data}')


def main(args=None):
    rclpy.init(args=args)

    node = AMRStatusPublisher()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass

    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
