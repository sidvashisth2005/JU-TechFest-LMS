"""Decides track speeds: manual commands from the dashboard, or follow-the-target mode.

Follow mode is the hackathon PD controller, generalised from a green ball's radius to any
detection box: steer to keep the target centred, drive forward when it is far, hold when it
is at a comfortable distance, back off when it is too close.
"""

import time

from rover.config import RoverConfig
from rover.vision import Det

DIRECTIONS = ("forward", "backward", "left", "right", "stop")
FOLLOW_LABELS = ("cow", "green_marker", "sheep")  # in order of preference; never follow people


class Controller:
    def __init__(self, cfg: RoverConfig):
        self.cfg = cfg
        self.mode = "idle"
        self._manual: tuple[float, float] = (0.0, 0.0)
        self._manual_at = 0.0
        self._target_id: int | None = None
        self._target_seen_at = 0.0
        self._prev_error = 0.0
        self.target: Det | None = None
        self.state = "idle"  # human-readable: what the controller is doing

    # ---------- commands ----------
    def set_mode(self, mode: str) -> None:
        if mode not in ("idle", "manual", "follow"):
            raise ValueError(f"unknown mode {mode}")
        self.mode = mode
        self._manual = (0.0, 0.0)
        self._target_id = None
        self._prev_error = 0.0

    def manual(self, direction: str, speed_pct: float, now: float | None = None) -> None:
        if direction not in DIRECTIONS:
            raise ValueError(f"unknown direction {direction}")
        if self.mode != "manual":
            self.set_mode("manual")
        v = max(0.0, min(100.0, speed_pct)) / 100 * self.cfg.max_dps
        turn = self.cfg.turn_sign * v * 0.6
        self._manual = {
            "forward": (v, v),
            "backward": (-v, -v),
            "left": (-turn, turn),
            "right": (turn, -turn),
            "stop": (0.0, 0.0),
        }[direction]
        self._manual_at = now if now is not None else time.time()

    # ---------- control loop ----------
    def step(self, dets: list[Det], frame_w: int, frame_h: int, now: float) -> tuple[float, float]:
        if self.mode == "manual":
            if now - self._manual_at > self.cfg.manual_timeout_s:
                self.state = "manual: waiting for command"
                return 0.0, 0.0
            self.state = "manual"
            return self._manual
        if self.mode == "follow":
            return self._follow(dets, frame_w, frame_h, now)
        self.state = "idle"
        return 0.0, 0.0

    def _pick(self, dets: list[Det]) -> Det | None:
        if self._target_id is not None:
            for d in dets:
                if d.track_id == self._target_id:
                    return d
        for label in FOLLOW_LABELS:
            cands = [d for d in dets if d.label == label]
            if cands:
                return max(cands, key=lambda d: d.height)  # nearest looks tallest
        return None

    def _follow(self, dets, frame_w, frame_h, now) -> tuple[float, float]:
        cfg = self.cfg
        target = self._pick(dets)
        self.target = target
        if target is None:
            if now - self._target_seen_at > cfg.lost_after_s:
                self._target_id = None
                self.state = "follow: searching"
            return 0.0, 0.0
        self._target_id = target.track_id
        self._target_seen_at = now

        # steering: error in "legacy pixels" (the PD gains were tuned on a 320 px wide frame)
        error = (target.cx - frame_w / 2) / frame_w * 320
        turn = cfg.kp * error + cfg.kd * (error - self._prev_error)
        self._prev_error = error
        if abs(error) < cfg.center_tolerance * 320:
            turn = 0.0
        turn = max(-cfg.rotate_limit_dps, min(cfg.rotate_limit_dps, turn)) * cfg.turn_sign

        size = target.height / frame_h
        if size > cfg.target_full:
            self.state = "follow: too close, backing off"
            return -cfg.follow_reverse_dps, -cfg.follow_reverse_dps
        if size > cfg.target_near:
            self.state = "follow: holding distance"
            forward = 0.0
        elif size > cfg.target_far:
            self.state = "follow: approaching slowly"
            forward = cfg.follow_forward_dps * 0.5
        else:
            self.state = "follow: approaching"
            forward = cfg.follow_forward_dps
        return forward + turn, forward - turn
