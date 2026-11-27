"""Agent ROS front-end: publish requests on /agent/command, read /agent/response."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('offline', default_value='false'),
        DeclareLaunchArgument('backend', default_value='auto'),
        # no `name=` override: it would rename every node in the process, including the agent's backend client
        Node(package='amr_agent', executable='agent_node', output='screen',
             parameters=[{'use_sim_time': True, 'offline': LaunchConfiguration('offline'),
                         'backend': LaunchConfiguration('backend')}]),
    ])
