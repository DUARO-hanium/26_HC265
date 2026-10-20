"""Compatibility entry point for the pre-0.3 module path."""

from .calibration.handeye_node import HandEyeCalibrator, main

__all__ = ['HandEyeCalibrator', 'main']
