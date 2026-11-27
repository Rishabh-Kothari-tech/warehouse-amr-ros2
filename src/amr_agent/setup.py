import os
from glob import glob

from setuptools import setup

package_name = 'amr_agent'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Rishabh Kothari',
    maintainer_email='251034528+Rishabh-Kothari-tech@users.noreply.github.com',
    description='LLM tool-calling agent for warehouse AMR missions',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'chat = amr_agent.chat:main',
            'agent_node = amr_agent.agent_node:main',
            'evaluate = amr_agent.evaluate:main',
        ],
    },
)
