"""Operations front-end: the agent (ROS topic interface) + the web dashboard on http://localhost:8765.
Start after warehouse_simulation, amr_navigation and warehouse_tasks."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('backend', default_value='auto'),
        DeclareLaunchArgument('port', default_value='8765'),
        Node(package='amr_agent', executable='agent_node', output='screen',
             parameters=[{'use_sim_time': True, 'backend': LaunchConfiguration('backend')}]),
        Node(package='amr_dashboard', executable='dashboard', output='screen',
             parameters=[{'use_sim_time': True, 'port': LaunchConfiguration('port')}]),
    ])
