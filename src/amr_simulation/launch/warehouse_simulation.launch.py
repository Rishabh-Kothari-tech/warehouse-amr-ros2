import os

from launch import LaunchDescription
from launch.actions import RegisterEventHandler, EmitEvent
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch_ros.actions import Node

from ament_index_python.packages import get_package_share_directory

from webots_ros2_driver.webots_launcher import WebotsLauncher
from webots_ros2_driver.webots_controller import WebotsController
from webots_ros2_driver.wait_for_controller_connection import WaitForControllerConnection


def generate_launch_description():

    package_dir = get_package_share_directory('amr_simulation')

    world_path = os.path.join(
        package_dir,
        'worlds',
        'warehouse.wbt'
    )

    robot_description_path = os.path.join(
        package_dir,
        'resource',
        'warehouse_amr_webots.urdf'
    )

    controller_config_path = os.path.join(
        package_dir,
        'resource',
        'controllers.yaml'
    )

    webots = WebotsLauncher(
        world=world_path,
        ros2_supervisor=True
    )


    # Publish the full robot URDF (including the <ros2_control> tag) from the start.
    # In Jazzy the controller_manager initializes its hardware from the FIRST message on
    # /robot_description, so it must never see an empty placeholder.
    with open(robot_description_path, 'r') as urdf_file:
        robot_description_xml = urdf_file.read()

    robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        output='screen',
        parameters=[{
            'robot_description': robot_description_xml,
            'use_sim_time': True
        }]
    )

    # base_footprint -> base_link now comes from the URDF (base_footprint_joint),
    # so the separate static_transform_publisher was removed to avoid a duplicate TF edge.

    robot_driver = WebotsController(
        robot_name='WarehouseAMR',
        parameters=[
            {
                'robot_description': robot_description_path,
                'use_sim_time': True,
                'set_robot_state_publisher': False
            },
            controller_config_path
        ],
        remappings=[
            ('/diffdrive_controller/cmd_vel', '/cmd_vel'),
            ('/diffdrive_controller/odom', '/odom')
        ],
        respawn=True
    )

    joint_state_spawner = Node(
        package='controller_manager',
        executable='spawner',
        arguments=[
            'joint_state_broadcaster',
            '--controller-manager-timeout',
            '50'
        ],
        output='screen'
    )

    diff_drive_spawner = Node(
        package='controller_manager',
        executable='spawner',
        arguments=[
            'diffdrive_controller',
            '--controller-manager-timeout',
            '50'
        ],
        output='screen'
    )

    waiting_nodes = WaitForControllerConnection(
        target_driver=robot_driver,
        nodes_to_start=[
            joint_state_spawner,
            diff_drive_spawner
        ]
    )

    return LaunchDescription([
        webots,
        webots._supervisor,
        robot_state_publisher,
        robot_driver,
        waiting_nodes,

        RegisterEventHandler(
            event_handler=OnProcessExit(
                target_action=webots,
                on_exit=[
                    EmitEvent(event=Shutdown())
                ]
            )
        )
    ])
