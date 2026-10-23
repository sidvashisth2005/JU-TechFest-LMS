"""Rover tuning in one place. Values marked (legacy) come from the hackathon rover script."""

from dataclasses import dataclass


@dataclass
class RoverConfig:
    rover_id: str = "rover1"
    # BrickPi3 ports (legacy): left track = D, right track = C, ultrasonic = sensor port 2
    left_port: str = "PORT_D"
    right_port: str = "PORT_C"
    ultrasonic_port: str = "PORT_2"
    # Flip if the rover turns away from the target on the first hardware test.
    turn_sign: int = 1
    # Flip if "forward" drives the rover backwards.
    drive_sign: int = 1

    # speeds in motor degrees/second
    max_dps: float = 600
    follow_forward_dps: float = 260  # (legacy FORWARD_SPEED)
    follow_reverse_dps: float = 300  # (legacy REVERSE_SPEED)
    rotate_limit_dps: float = 320  # (legacy ROTATE_LIMIT)
    kp: float = 0.32  # (legacy) dps per pixel of error at 320 px width
    kd: float = 0.18  # (legacy)
    center_tolerance: float = 0.09  # fraction of frame width (legacy 30 px of 320)

    # how close the target is, as box height / frame height
    target_far: float = 0.35  # smaller: drive towards it
    target_near: float = 0.55  # between near and full: hold position
    target_full: float = 0.75  # larger: back off
    lost_after_s: float = 1.0  # stop when the target hasn't been seen for this long

    # safety
    stop_distance_cm: float = 20  # block forward motion closer than this (env ROVER_STOP_CM)
    close_echo_window_s: float = 1.0  # "no echo" right after a close reading means too close, not clear
    manual_timeout_s: float = 0.5  # manual drive stops if commands stop arriving (watchdog)
    battery_min_v: float = 9.0  # refuse to drive below this
    # a person whose box is taller than this fraction of the frame is close: no forward motion
    # The Pi camera's view is narrow: a person 1 m away already fills ~75% of the frame height,
    # so only a box that nearly fills it means "about to touch". 0 = off. (env ROVER_PERSON_STOP)
    person_stop_frac: float = 0.85
    person_min_conf: float = 0.4

    loop_hz: float = 20  # motor/safety loop; the camera + detector run in their own thread
    status_publish_s: float = 1.0
