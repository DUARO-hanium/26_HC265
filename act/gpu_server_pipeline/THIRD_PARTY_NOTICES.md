# Third-party notices

This project integrates with, but does not vendor, the following projects:

- [LeRobot](https://github.com/huggingface/lerobot), Apache-2.0. The runtime
  uses the official LeRobot 0.6.0 ACT policy, dataset API, asynchronous
  `PolicyServer`, `RobotClient`, preprocessing, postprocessing, and transport.
- [ROBOTIS OpenManipulator](https://github.com/ROBOTIS-GIT/open_manipulator),
  Apache-2.0. The ROS 2 adapter expects its Jazzy controller graph and
  Dynamixel hardware interface to be installed separately.
- [ROS 2](https://github.com/ros2), mostly Apache-2.0/BSD-3-Clause components.
- [Hugging Face Accelerate](https://github.com/huggingface/accelerate),
  Apache-2.0, used through LeRobot for distributed training.

All trademarks belong to their respective owners. Refer to each dependency's
distribution for its complete license and notices.
