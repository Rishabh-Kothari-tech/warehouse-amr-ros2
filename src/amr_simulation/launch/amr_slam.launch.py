import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, TimerAction, ExecuteProcess
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    package_dir = get_package_share_directory('amr_simulation')

    slam_config = os.path.join(
        package_dir, 'resource', 'slam_config.yaml'
    )

    slam_node = Node(
        package='slam_toolbox',
        executable='async_slam_toolbox_node',
        name='slam_toolbox',
        output='screen',
        parameters=[slam_config, {'use_sim_time': True}],
        remappings=[('scan', '/scan')]
    )

    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        output='screen',
        parameters=[{'use_sim_time': True}],
        condition=IfCondition(LaunchConfiguration('use_rviz'))
    )

    activate_slam = TimerAction(
        period=5.0,
        actions=[
            ExecuteProcess(
                cmd=[
                    'bash', '-c',
                    'source /opt/ros/jazzy/setup.bash && '
                    'ros2 lifecycle set /slam_toolbox configure && '
                    'ros2 lifecycle set /slam_toolbox activate'
                ],
                output='screen'
            )
        ]
    )

    return LaunchDescription([
        DeclareLaunchArgument('use_rviz', default_value='true'),
        slam_node,
        rviz_node,
        activate_slam
    ])
