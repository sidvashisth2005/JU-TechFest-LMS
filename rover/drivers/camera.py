"""Camera sources. All return BGR frames from `read()` (latest frame, never blocks long).

make_camera("webcam")          laptop/USB camera 0   ("webcam:1" for another index)
make_camera("video:cows.mp4")  loop a video file (testing detection without a barn)
make_camera("synthetic")       a green ball wandering over a field (tests follow mode)
make_camera("picamera2")       Pi Camera (final build)
make_camera("pixy2")           Pixy2 raw frames over USB (temporary camera)
"""

import math
import threading
import time

import cv2
import numpy as np


class Camera:
    name = "camera"

    def __init__(self):
        self._frame: np.ndarray | None = None
        self._lock = threading.Lock()
        self._running = True
        self.fps = 0.0
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _grab(self) -> np.ndarray | None:
        raise NotImplementedError

    def _loop(self) -> None:
        count, t0 = 0, time.time()
        while self._running:
            frame = self._grab()
            if frame is None:
                time.sleep(0.05)
                continue
            with self._lock:
                self._frame = frame
            count += 1
            if time.time() - t0 >= 2:
                self.fps = count / (time.time() - t0)
                count, t0 = 0, time.time()

    def read(self) -> np.ndarray | None:
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def close(self) -> None:
        self._running = False
        self._thread.join(timeout=2)


class OpenCVCamera(Camera):
    """Webcam/USB camera or a video file (looped)."""

    def __init__(self, source: int | str, width: int = 640, height: int = 480):
        self.source = source
        self.name = f"webcam {source}" if isinstance(source, int) else f"video {source}"
        self.cap = cv2.VideoCapture(source)
        if not self.cap.isOpened():
            raise RuntimeError(f"cannot open camera/video {source!r}")
        if isinstance(source, int):
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self._delay = 0.0
        else:
            fps = self.cap.get(cv2.CAP_PROP_FPS) or 25
            self._delay = 1.0 / fps  # play files at their own speed
        super().__init__()

    def _grab(self):
        ok, frame = self.cap.read()
        if not ok and not isinstance(self.source, int):
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self.cap.read()
        if self._delay:
            time.sleep(self._delay)
        return frame if ok else None

    def close(self):
        super().close()
        self.cap.release()


class SyntheticCamera(Camera):
    """A green ball drifting over a barn floor, for testing follow mode anywhere.

    (Not grass: the legacy green detector would lock onto a green field. Real fields are why
    the final rover uses YOLO cow detection.)
    """

    name = "synthetic"

    def __init__(self, width: int = 640, height: int = 480):
        self.w, self.h = width, height
        self.t0 = time.time()
        super().__init__()

    def _grab(self):
        time.sleep(1 / 30)
        t = time.time() - self.t0
        frame = np.full((self.h, self.w, 3), (70, 100, 135), np.uint8)  # dirt floor (BGR)
        frame[: self.h // 3] = (200, 170, 120)  # sky
        x = int(self.w / 2 + self.w * 0.35 * math.sin(t * 0.5))
        r = int(30 + 25 * (1 + math.sin(t * 0.23)))  # approaches and recedes
        cv2.circle(frame, (x, int(self.h * 0.6)), r, (40, 200, 40), -1)
        return frame


class Picamera2Camera(Camera):
    name = "picamera2"

    def __init__(self, width: int = 640, height: int = 480):
        from picamera2 import Picamera2  # only on the Pi

        self.cam = Picamera2()
        # "RGB888" in picamera2 is BGR byte order in memory, which is what OpenCV expects
        self.cam.configure(self.cam.create_video_configuration(main={"format": "RGB888", "size": (width, height)}))
        self.cam.start()
        super().__init__()

    def _grab(self):
        return self.cam.capture_array()

    def close(self):
        super().close()
        self.cam.stop()


class Pixy2Camera(Camera):
    """Pixy2 raw Bayer frames (316x208) with the clean-up pipeline from pi-tools/pixy_stream.py."""

    name = "pixy2"
    W, H = 316, 208

    def __init__(self, brightness: int = 90, average: int = 3):
        import pixy  # SWIG module built on the Pi (see CLAUDE.md, Pixy2 section)

        self.pixy = pixy
        for _ in range(10):
            if pixy.init() >= 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Pixy2 not found")
        pixy.cam_set_u8("cam_setBrightness", brightness)
        pixy.video_stop()
        self._buf = bytearray(self.W * self.H)
        self._acc = None
        self._wb = None
        self._levels = None
        self._alpha = 1.0 / max(1, average)
        super().__init__()

    def _grab(self):
        # grab and process in this one thread: the SWIG calls hold the GIL
        if self.pixy.video_get_raw_frame(self._buf) <= 0:
            return None
        raw = np.frombuffer(bytes(self._buf), dtype=np.uint8).reshape(self.H, self.W)
        img = cv2.cvtColor(raw, cv2.COLOR_BayerRG2BGR_EA).astype(np.float32)
        if self._acc is None:
            self._acc = img.copy()
        else:
            cv2.accumulateWeighted(img, self._acc, self._alpha)
        means = np.array(cv2.mean(self._acc)[:3]) + 1e-3
        gains = means.mean() / means
        self._wb = gains if self._wb is None else 0.9 * self._wb + 0.1 * gains
        img = cv2.convertScaleAbs(cv2.multiply(self._acc, (*self._wb, 0)))
        hist = cv2.calcHist([cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)], [0], None, [256], [0, 256]).ravel()
        cdf = hist.cumsum() / hist.sum()
        lv = np.array([float(np.searchsorted(cdf, 0.01)), float(np.searchsorted(cdf, 0.99))])
        lv[1] = max(lv[1], lv[0] + 32)
        self._levels = lv if self._levels is None else 0.9 * self._levels + 0.1 * lv
        lo, hi = self._levels
        lut = np.clip((np.arange(256) - lo) * 255.0 / (hi - lo), 0, 255).astype(np.uint8)
        return cv2.LUT(img, lut)

    def close(self):
        super().close()
        self.pixy.video_resume()


def make_camera(spec: str) -> Camera:
    if spec == "synthetic":
        return SyntheticCamera()
    if spec == "picamera2":
        return Picamera2Camera()
    if spec == "pixy2":
        return Pixy2Camera()
    if spec.startswith("webcam"):
        _, _, idx = spec.partition(":")
        return OpenCVCamera(int(idx or 0))
    if spec.startswith("video:"):
        return OpenCVCamera(spec[len("video:") :])
    raise ValueError(f"unknown camera {spec!r}")
