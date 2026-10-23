"""Stream Pixy2 raw camera frames as MJPEG over HTTP, with image clean-up.

Run on the Pi:   ~/lms-venv/bin/python pixy_stream.py [--port 8000] [--brightness 90]
Open on laptop:  http://<pi-ip>:8000   (or http://localhost:8000 through an ssh -L tunnel)

Endpoints:
  /                 viewer page with a brightness slider
  /stream.mjpg      MJPEG stream
  /snapshot.jpg     single processed frame
  /set?brightness=N camera brightness 0-255 (auto-exposure target)

Needs the Pixy2 SWIG module built with the LMS additions
(video_stop / video_resume / video_get_raw_frame / cam_set_u8 / cam_get).
"""
import argparse
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np
import pixy

W, H = 316, 208

PAGE = b"""<!doctype html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Pixy2 live</title>
<style>body{margin:0;background:#111;color:#ddd;font-family:sans-serif;text-align:center}
img{max-width:100%;margin-top:12px}label{display:inline-block;margin:10px}</style></head>
<body><h3>Pixy2 live feed</h3><img src="/stream.mjpg"><br>
<label>Brightness <input type="range" min="0" max="255" id="b"
 onchange="fetch('/set?brightness='+this.value).then(r=>r.text()).then(t=>document.getElementById('v').textContent=t)"></label>
<span id="v"></span>
<script>fetch('/set').then(r=>r.text()).then(t=>{document.getElementById('v').textContent=t;
document.getElementById('b').value=parseInt(t.split('=')[1])})</script></body></html>"""


class Camera:
    def __init__(self, brightness, scale, average):
        for _ in range(10):
            if pixy.init() >= 0:
                break
            time.sleep(1)
        else:
            raise SystemExit("Pixy2 not found (check USB cable)")
        if brightness is not None:
            pixy.cam_set_u8("cam_setBrightness", brightness)
        pixy.video_stop()
        self.scale = scale
        self.average = average
        self.lock = threading.Lock()  # serialises all USB calls
        self._buf = bytearray(W * H)
        self._acc = None
        self._wb = None
        self._levels = None
        self._jpeg = None
        self._cond = threading.Condition()
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def brightness(self, value=None):
        with self.lock:
            if value is not None:
                pixy.video_resume()
                pixy.cam_set_u8("cam_setBrightness", value)
                pixy.video_stop()
            return pixy.cam_get("cam_getBrightness")

    def _grab(self):
        with self.lock:
            n = pixy.video_get_raw_frame(self._buf)
        if n <= 0:
            return None
        return np.frombuffer(bytes(self._buf), dtype=np.uint8).reshape(H, W)

    def _process(self, raw):
        # edge-aware demosaic gives fewer colour fringes than the bilinear default
        img = cv2.cvtColor(raw, cv2.COLOR_BayerRG2BGR_EA).astype(np.float32)

        # temporal denoise: running average over recent frames
        if self._acc is None:
            self._acc = img.copy()
        else:
            cv2.accumulateWeighted(img, self._acc, 1.0 / self.average)

        # grey-world white balance, smoothed so colours don't flicker
        means = np.array(cv2.mean(self._acc)[:3]) + 1e-3
        gains = means.mean() / means
        self._wb = gains if self._wb is None else 0.9 * self._wb + 0.1 * gains
        img = cv2.convertScaleAbs(cv2.multiply(self._acc, (*self._wb, 0)))

        # auto levels: stretch 1st..99th percentile of brightness, smoothed over time
        hist = cv2.calcHist([cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)], [0], None, [256], [0, 256]).ravel()
        cdf = hist.cumsum() / hist.sum()
        lo, hi = float(np.searchsorted(cdf, 0.01)), float(np.searchsorted(cdf, 0.99))
        lv = np.array([lo, max(hi, lo + 32)])
        self._levels = lv if self._levels is None else 0.9 * self._levels + 0.1 * lv
        lo, hi = self._levels
        lut = np.clip((np.arange(256) - lo) * 255.0 / (hi - lo), 0, 255).astype(np.uint8)
        img = cv2.LUT(img, lut)

        # sharpen at native size (cheap), then upscale for display
        blur = cv2.GaussianBlur(img, (0, 0), 1.0)
        img = cv2.addWeighted(img, 1.5, blur, -0.5, 0)
        if self.scale > 1:
            img = cv2.resize(img, (W * self.scale, H * self.scale), interpolation=cv2.INTER_CUBIC)
        return img

    def _loop(self):
        # grab and process in one thread: the SWIG calls hold the GIL, so a
        # separate grab thread would starve processing
        while self._running:
            raw = self._grab()
            if raw is None:
                time.sleep(0.05)
                continue
            ok, jpg = cv2.imencode(".jpg", self._process(raw), [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                with self._cond:
                    self._jpeg = jpg.tobytes()
                    self._cond.notify_all()

    def wait_frame(self):
        with self._cond:
            self._cond.wait(timeout=2)
            return self._jpeg

    def close(self):
        self._running = False
        time.sleep(0.2)
        with self.lock:
            pixy.video_resume()


def make_handler(cam):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, body, ctype):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/":
                self._send(PAGE, "text/html")
            elif url.path == "/snapshot.jpg":
                self._send(cam.wait_frame() or b"", "image/jpeg")
            elif url.path == "/set":
                q = parse_qs(url.query)
                value = int(q["brightness"][0]) if "brightness" in q else None
                if value is not None:
                    value = max(0, min(255, value))
                self._send(f"brightness={cam.brightness(value)}".encode(), "text/plain")
            elif url.path == "/stream.mjpg":
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.end_headers()
                try:
                    while True:
                        jpg = cam.wait_frame()
                        if jpg:
                            self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n")
                except (BrokenPipeError, ConnectionResetError):
                    pass
            else:
                self.send_error(404)

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--brightness", type=int, default=90, help="0-255, auto-exposure target")
    ap.add_argument("--scale", type=int, default=2, help="upscale factor for display")
    ap.add_argument("--average", type=int, default=3, help="frames in temporal denoise (1 = off)")
    args = ap.parse_args()

    cam = Camera(args.brightness, args.scale, max(1, args.average))
    server = ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(cam))
    server.daemon_threads = True

    def shutdown(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print(f"Pixy2 stream on http://0.0.0.0:{args.port}  (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    finally:
        cam.close()
        server.server_close()
        sys.exit(0)


if __name__ == "__main__":
    main()
