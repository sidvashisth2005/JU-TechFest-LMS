"""Rover server: camera + detection + follow controller + safety, with an HTTP API.

On the Pi:     python -m rover.server --camera picamera2 --detector yolo:models/cow.onnx
Temporary:     python -m rover.server --camera pixy2 --detector green
On a laptop:   python -m rover.server --mock --camera webcam      (or --camera synthetic)

Endpoints (the dashboard reaches them through the backend's /api/rover proxy):
  GET  /status        mode, distance, battery, motor speeds, what the camera sees
  POST /control       {"direction": "forward|backward|left|right|stop", "speed": 0-100}
  POST /mode          {"mode": "idle|manual|follow"}
  GET  /stream.mjpg   annotated camera stream
  GET  /snapshot.jpg  one annotated frame
  POST /mock          {"distance_cm": 12, "battery_v": 11} (only with --mock, for testing safety)
"""

import argparse
import logging
import os
import threading
import time
from contextlib import asynccontextmanager

import cv2
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from common import topics
from common.schemas import Detection, DetectionsMsg, RoverStatusMsg
from rover.config import RoverConfig
from rover.controller import DIRECTIONS, Controller
from rover.drivers.brickpi import BrickPiHardware, MockHardware
from rover.drivers.camera import make_camera
from rover.safety import Safety
from rover.vision import IouTracker, annotate, make_detector

log = logging.getLogger("rover")


class Rover:
    def __init__(self, cfg: RoverConfig, camera: str, detector: str, mock: bool, mqtt_client=None):
        self.cfg = cfg
        self.mock = mock
        self.hw = MockHardware(cfg) if mock else BrickPiHardware(cfg)
        self.camera = make_camera(camera)
        self.detector = make_detector(detector)
        self.tracker = IouTracker()
        self.controller = Controller(cfg)
        self.safety = Safety(cfg)
        self.mqtt = mqtt_client
        self.lock = threading.Lock()  # guards controller commands vs the loop
        self.left = self.right = 0.0
        self.battery: float | None = None
        self.dets = []
        self.jpeg: bytes | None = None
        self.frame_cond = threading.Condition()
        self.loop_fps = 0.0
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    # ---------- loop ----------
    def _loop(self) -> None:
        period = 1.0 / self.cfg.loop_hz
        last_battery = last_status = 0.0
        count, t_fps = 0, time.time()
        while self._running:
            t = time.time()
            try:
                self._tick(t, last_battery_due=t - last_battery > 2.0)
                if t - last_battery > 2.0:
                    last_battery = t
                if t - last_status >= self.cfg.status_publish_s:
                    self._publish_status(t)
                    last_status = t
            except Exception:
                log.exception("control loop error; stopping motors")
                self.hw.stop()
                self.left = self.right = 0.0
            count += 1
            if t - t_fps >= 2:
                self.loop_fps = count / (t - t_fps)
                count, t_fps = 0, t
            time.sleep(max(0.0, period - (time.time() - t)))

    def _tick(self, now: float, last_battery_due: bool) -> None:
        frame = self.camera.read()
        if last_battery_due:
            self.battery = self.hw.battery_v()
        self.safety.update(self.hw.distance_cm(), now)
        dets = []
        h, w = (frame.shape[:2]) if frame is not None else (480, 640)
        if frame is not None:
            dets = self.tracker.update(self.detector.detect(frame))
        self.safety.update_people(dets, h)
        with self.lock:
            left, right = self.controller.step(dets, w, h, now)
        left, right = self.safety.filter(left, right, now, self.battery)
        cap = self.cfg.max_dps
        left, right = max(-cap, min(cap, left)), max(-cap, min(cap, right))
        if left == 0 and right == 0:
            self.hw.stop()
        else:
            self.hw.drive(left, right)
        self.left, self.right, self.dets = left, right, dets
        if dets and self.mqtt is not None:
            self._publish_detections(now, w, h, dets)
        if frame is not None:
            lines = [
                f"{self.controller.mode.upper()}  {self.controller.state}",
                f"L {left:+.0f}  R {right:+.0f} dps   dist "
                + ("--" if self.safety.distance is None else f"{self.safety.distance:.0f} cm"),
            ]
            if self.safety.reason:
                lines.append(f"STOP: {self.safety.reason}")
            out = annotate(frame, dets, self.controller.target, lines)
            ok, jpg = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                with self.frame_cond:
                    self.jpeg = jpg.tobytes()
                    self.frame_cond.notify_all()

    # ---------- MQTT ----------
    def status(self) -> dict:
        return {
            **RoverStatusMsg(
                rover_id=self.cfg.rover_id,
                mode=self.controller.mode,
                battery=self.battery,
                distance_cm=self.safety.distance,
                blocked=self.safety.reason is not None or self.safety.blocked(time.time()) or self.safety.person_close,
                left_dps=round(self.left, 1),
                right_dps=round(self.right, 1),
            ).model_dump(),
            "state": self.controller.state,
            "safety": self.safety.reason,
            "camera": self.camera.name,
            "detector": self.detector.name,
            "targets": sum(1 for d in self.dets if d.label != "person"),
            "fps": round(self.camera.fps, 1),
            "loop_hz": round(self.loop_fps, 1),
            "mock": self.mock,
        }

    def _publish_status(self, now: float) -> None:
        if self.mqtt is None:
            return
        s = self.status()
        msg = RoverStatusMsg(**{k: s[k] for k in RoverStatusMsg.model_fields if k in s})
        self.mqtt.publish(topics.rover_status(self.cfg.rover_id), msg.model_dump_json(), qos=0)

    def _publish_detections(self, now, w, h, dets) -> None:
        msg = DetectionsMsg(
            rover_id=self.cfg.rover_id,
            ts=now,
            frame_w=w,
            frame_h=h,
            detections=[
                Detection(label=d.label, confidence=d.confidence, box=d.box, track_id=d.track_id) for d in dets
            ],
        )
        self.mqtt.publish(topics.rover_detections(self.cfg.rover_id), msg.model_dump_json(), qos=0)

    def wait_frame(self) -> bytes | None:
        with self.frame_cond:
            self.frame_cond.wait(timeout=2)
            return self.jpeg

    def close(self) -> None:
        self._running = False
        self._thread.join(timeout=2)
        self.hw.close()
        self.camera.close()


class ControlIn(BaseModel):
    direction: str
    speed: float = Field(40, ge=0, le=100)


class ModeIn(BaseModel):
    mode: str


class MockIn(BaseModel):
    distance_cm: float | None = None
    battery_v: float | None = None


def make_app(rover: Rover) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        rover.close()

    app = FastAPI(title="LMS rover", lifespan=lifespan)

    @app.get("/status")
    def status():
        return rover.status()

    @app.post("/control")
    def control(body: ControlIn):
        if body.direction not in DIRECTIONS:
            raise HTTPException(400, f"direction must be one of {DIRECTIONS}")
        with rover.lock:
            rover.controller.manual(body.direction, body.speed)
        return {"ok": True, "mode": rover.controller.mode}

    @app.post("/mode")
    def mode(body: ModeIn):
        try:
            with rover.lock:
                rover.controller.set_mode(body.mode)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {"ok": True, "mode": rover.controller.mode}

    @app.get("/snapshot.jpg")
    def snapshot():
        jpg = rover.wait_frame()
        if jpg is None:
            raise HTTPException(503, "no camera frame yet")
        return Response(jpg, media_type="image/jpeg")

    @app.get("/stream.mjpg")
    def stream():
        def frames():
            while True:
                jpg = rover.wait_frame()
                if jpg:
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"

        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")

    @app.post("/mock")
    def mock(body: MockIn):
        if not rover.mock:
            raise HTTPException(403, "only available with --mock")
        rover.hw.mock_distance = body.distance_cm
        if body.battery_v is not None:
            rover.hw.mock_battery = body.battery_v
        return {"distance_cm": rover.hw.mock_distance, "battery_v": rover.hw.mock_battery}

    return app


def mqtt_connect(host: str):
    """Optional: publish status/detections to the backend broker (MQTT_USER/MQTT_PASSWORD env)."""
    import paho.mqtt.client as mqtt

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"lms-rover-{os.getpid()}")
    c.username_pw_set(os.environ.get("MQTT_USER", ""), os.environ.get("MQTT_PASSWORD", ""))
    c.reconnect_delay_set(1, 30)
    c.connect_async(host, int(os.environ.get("MQTT_PORT", 1883)))
    c.loop_start()
    return c


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mock", action="store_true", help="no BrickPi: simulated motors and ultrasonic")
    ap.add_argument("--camera", default="synthetic", help="webcam[:N] | video:PATH | synthetic | picamera2 | pixy2")
    ap.add_argument("--detector", default="green", help="green | yolo:PATH.onnx")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--mqtt", default=os.environ.get("ROVER_MQTT_HOST"), help="broker host for status/detections")
    ap.add_argument("--turn-sign", type=int, choices=[-1, 1], default=1)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    cfg = RoverConfig(turn_sign=args.turn_sign)
    client = mqtt_connect(args.mqtt) if args.mqtt else None
    rover = Rover(cfg, args.camera, args.detector, args.mock, client)
    log.info("rover up: camera=%s detector=%s mock=%s", rover.camera.name, rover.detector.name, args.mock)
    uvicorn.run(make_app(rover), host="0.0.0.0", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
