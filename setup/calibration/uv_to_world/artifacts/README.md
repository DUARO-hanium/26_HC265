# Calibration bundle contract

Real calibration results are machine-specific and must not be committed as
package defaults. Store each accepted calibration in:

```text
~/.ros/uv_to_world/calibrations/<profile>/
  camera_intrinsics.yaml
  eye_to_hand.yaml
  environment_planes.yaml
  manifest.yaml
  reports/
```

Required runtime files:

- `camera_intrinsics.yaml`: ROS CameraInfo calibration produced by
  `camera_calibration` (`ost.yaml` format).
- `eye_to_hand.yaml`: `link0 -> camera1_optical_frame`, with
  `calibration.quality_passed: true`.
- `environment_planes.yaml`: ROS parameters for the named worktop and floor
  projections. Packaged values are examples, not measurements.

`manifest.yaml` and `reports/` are recommended provenance records and are not
read by runtime nodes.
