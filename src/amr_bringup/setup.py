from setuptools import find_packages, setup

package_name = 'amr_bringup'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='rishabh',
    maintainer_email='rishabh@todo.todo',
    description='TODO: Package description',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
    'console_scripts': [
        'status_publisher = amr_bringup.status_publisher:main',
        'status_monitor = amr_bringup.status_monitor:main',
        'velocity_controller = amr_bringup.velocity_controller:main',
    ],
},
)
