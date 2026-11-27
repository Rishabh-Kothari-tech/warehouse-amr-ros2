"""Localization (map_server + AMCL) and Nav2 navigation for the warehouse AMR.

Run this INSTEAD of amr_slam.launch.py (mapping and localization are separate modes),
with warehouse_simulation.launch.py already running.
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_dir = get_package_share_directory('amr_simulation')
    default_params = os.path.join(pkg_dir, 'config', 'nav2_params.yaml')
    default_map = os.path.expanduser('~/warehouse_amr_ws/maps/warehouse_map_v4.yaml')
    rviz_config = os.path.join(get_package_share_directory('nav2_bringup'), 'rviz', 'nav2_default_view.rviz')

    params = LaunchConfiguration('params_file')
    map_yaml = LaunchConfiguration('map')
    use_rviz = LaunchConfiguration('use_rviz')
    common = [params, {'use_sim_time': True}]

    localization_nodes = ['map_server', 'amcl']
    navigation_nodes = ['controller_server', 'planner_server', 'behavior_server',
                        'velocity_smoother', 'collision_monitor', 'bt_navigator', 'waypoint_follower']

    return LaunchDescription([
        DeclareLaunchArgument('params_file', default_value=default_params),
        DeclareLaunchArgument('map', default_value=default_map),
        DeclareLaunchArgument('use_rviz', default_value='true'),

        # ---------- Localization ----------
        Node(package='nav2_map_server', executable='map_server', name='map_server', output='screen',
             parameters=common + [{'yaml_filename': map_yaml}]),
        Node(package='nav2_amcl', executable='amcl', name='amcl', output='screen', parameters=common),
        Node(package='nav2_lifecycle_manager', executable='lifecycle_manager', name='lifecycle_manager_localization',
             output='screen', parameters=[{'use_sim_time': True, 'autostart': True, 'node_names': localization_nodes}]),

        # ---------- Navigation ----------
        # cmd_vel chain: controller -> cmd_vel_nav -> velocity_smoother -> cmd_vel_smoothed
        #                -> collision_monitor -> /cmd_vel (TwistStamped) -> diffdrive_controller
        Node(package='nav2_controller', executable='controller_server', name='controller_server', output='screen',
             parameters=common, remappings=[('cmd_vel', 'cmd_vel_nav')]),
        Node(package='nav2_planner', executable='planner_server', name='planner_server', output='screen',
             parameters=common),
        Node(package='nav2_behaviors', executable='behavior_server', name='behavior_server', output='screen',
             parameters=common, remappings=[('cmd_vel', 'cmd_vel_nav')]),
        Node(package='nav2_velocity_smoother', executable='velocity_smoother', name='velocity_smoother',
             output='screen', parameters=common, remappings=[('cmd_vel', 'cmd_vel_nav')]),
        Node(package='nav2_collision_monitor', executable='collision_monitor', name='collision_monitor',
             output='screen', parameters=common),
        Node(package='nav2_bt_navigator', executable='bt_navigator', name='bt_navigator', output='screen',
             parameters=common),
        Node(package='nav2_waypoint_follower', executable='waypoint_follower', name='waypoint_follower',
             output='screen', parameters=common),
        Node(package='nav2_lifecycle_manager', executable='lifecycle_manager', name='lifecycle_manager_navigation',
             output='screen', parameters=[{'use_sim_time': True, 'autostart': True, 'node_names': navigation_nodes}]),

        Node(package='rviz2', executable='rviz2', name='rviz2', output='screen',
             arguments=['-d', rviz_config], parameters=[{'use_sim_time': True}],
             condition=IfCondition(use_rviz)),
    ])
