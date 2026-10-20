from glob import glob
from setuptools import find_packages, setup

package_name = 'uv_to_world'

setup(
    name=package_name,
    version='0.3.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml', 'README.md', 'LICENSE']),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
        ('share/' + package_name + '/config/calibration',
         glob('config/calibration/*.yaml')),
        ('share/' + package_name + '/config/runtime',
         glob('config/runtime/*.yaml')),
        ('share/' + package_name + '/launch', glob('launch/*.launch.py')),
        ('share/' + package_name + '/docs', glob('docs/*.md')),
        ('share/' + package_name + '/artifacts', glob('artifacts/*.md')),
        ('share/' + package_name + '/scripts/windows', glob('scripts/windows/*.ps1')),
        ('share/' + package_name + '/scripts/linux', glob('scripts/linux/*.sh')),
    ],
    install_requires=['setuptools'],
    tests_require=['pytest'],
    zip_safe=True,
    maintainer='YWhero',
    maintainer_email='YWhero@users.noreply.github.com',
    description='Back-project RGB pixels onto a known plane in the world frame.',
    license='Apache-2.0',
    entry_points={'console_scripts': [
        'plane_projection = uv_to_world.runtime.plane_projection_node:main',
        'handeye_calibrator = uv_to_world.calibration.handeye_node:main',
        'calibrated_tf_publisher = uv_to_world.runtime.calibrated_tf_node:main',
        'generate_charuco_board = uv_to_world.calibration.generate_board:main',
    ]},
)
