import os
from glob import glob

from setuptools import setup

package_name = 'amr_tasks'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Rishabh Kothari',
    maintainer_email='251034528+Rishabh-Kothari-tech@users.noreply.github.com',
    description='Warehouse task layer: stations, mission executor on Nav2, multi-order scheduler',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'warehouse_manager = amr_tasks.warehouse_manager:main',
        ],
    },
)
