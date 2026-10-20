# In-package-socks reference profile

This profile was measured from `HYHero/in_package_socks_0805` at the pinned revision
recorded in `training_start_pose.episode0.json`. It is **not a universal OMX safety
profile**. Audit joint calibration, limits, camera roles, workspace, start pose, and
gripper mechanics before copying it to another robot.

`profile.env.example` enables a task-specific gripper latch that preserves a strong
closed target while the ACT output remains inside the learned closed band. Generic
repository defaults keep this feature disabled. Copy it to `profile.env` only after
reviewing it; that untracked file is loaded by the runtime.
