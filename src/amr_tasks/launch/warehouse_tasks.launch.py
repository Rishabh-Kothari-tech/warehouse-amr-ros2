"""Warehouse task layer. Start after warehouse_simulation + amr_navigation are up."""
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(package='amr_tasks', executable='warehouse_manager', name='warehouse_manager', output='screen',
             parameters=[{'use_sim_time': True}]),
    ])
