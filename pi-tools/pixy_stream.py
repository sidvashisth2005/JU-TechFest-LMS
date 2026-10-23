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
import json
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np
import pixy

W, H = 316, 208
SERVO_STEP = 15  # servo units per step when moving the pan-tilt
SERVO_STEP_DELAY = 0.03  # seconds between steps
SERVO_FILE = Path.home() / ".pixy_servo.json"
MAX_GRAB_FAILURES = 60  # ~3 s of failed frame grabs -> exit and let the respawn loop reconnect


def load_servo() -> tuple[int, int]:
    """Last commanded pan/tilt, so a restart doesn't jerk the camera back to centre."""
    try:
        d = json.loads(SERVO_FILE.read_text())
        return int(d["pan"]), int(d["tilt"])
    except (OSError, ValueError, KeyError):
        return 500, 500


def save_servo(pan: int, tilt: int) -> None:
    try:
        SERVO_FILE.write_text(json.dumps({"pan": pan, "tilt": tilt}))
    except OSError:
        pass


PAGE = b"""<!doctype html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Pixy2 live</title>
<style>body{margin:0;background:#111;color:#ddd;font-family:sans-serif;text-align:center}
img{max-width:100%;margin-top:12px}label{display:inline-block;margin:10px}</style></head>
<body><h3>Pixy2 live feed</h3><img src="/stream.mjpg"><br>
<label>Brightness <input type="range" min="0" max="255" id="b"
 onchange="fetch('/set?brightness='+this.value).then(r=>r.text()).then(t=>document.getElementById('v').textContent=t)"></label>
<span id="v"></span>
<div style="margin:8px">Pan-tilt:
 <button onclick="mv(0,60)">Up</button> <button onclick="mv(0,-60)">Down</button>
 <button onclick="mv(-60,0)">Left</button> <button onclick="mv(60,0)">Right</button>
 <button onclick="fetch('/servo?pan=500&tilt=500').then(r=>r.text()).then(s)">Center</button>
 <span id="sv"></span></div>
<script>fetch('/set').then(r=>r.text()).then(t=>{document.getElementById('v').textContent=t;
document.getElementById('b').value=parseInt(t.split('=')[1])});
function s(t){document.getElementById('sv').textContent=t}
function mv(dp,dt){fetch('/servo?dpan='+dp+'&dtilt='+dt).then(r=>r.text()).then(s)}
fetch('/servo').then(r=>r.text()).then(s);
// arrow keys move the pan-tilt (Shift = fine steps), C centres it
document.addEventListener('keydown',e=>{const k=e.shiftKey?20:60;
 const m={ArrowUp:[0,k],ArrowDown:[0,-k],ArrowLeft:[-k,0],ArrowRight:[k,0]}[e.key];
 if(m){e.preventDefault();mv(m[0],m[1])}
 else if(e.key==='c'||e.key==='C'){fetch('/servo?pan=500&tilt=500').then(r=>r.text()).then(s)}});
// focus helper: higher = sharper; turn the lens slowly and stop at the highest number
let best=0;setInterval(()=>fetch('/focus').then(r=>r.text()).then(t=>{const v=+t;best=Math.max(best,v);
 document.getElementById('f').textContent=v;document.getElementById('fb').textContent=best;
 document.getElementById('fbar').style.width=Math.min(100,best?100*v/best:0)+'%'}),400);
</script><p style="color:#888">Keys: arrows move the camera (Shift = fine), C = centre</p>
<div style="margin:10px auto;max-width:420px">Focus score <b id="f" style="font-size:28px;color:#7f7">0</b>
 &nbsp; best <b id="fb">0</b> <button onclick="best=0">reset best</button>
 <div style="background:#333;height:12px;border-radius:6px;margin-top:6px"><div id="fbar"
 style="background:#7f7;height:12px;width:0;border-radius:6px"></div></div>
 <p style="color:#888">Point at printed text 50 cm away and turn the lens slowly:
 the bar is full at the sharpest point seen.</p></div>
</body></html>"""


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
        self.pan, self.tilt = load_servo()
        self.focus: float | None = None
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

    def servo(self, pan=None, tilt=None, dpan=0, dtilt=0):
        """Pan-tilt kit on the Pixy2 servo port, positions 0..1000 (500 = centre).

        On this rover the kit is wired S0 = tilt (higher = up) and S1 = pan (higher = right).
        """
        with self.lock:
            target_pan = max(0, min(1000, (self.pan if pan is None else pan) + dpan))
            target_tilt = max(0, min(1000, (self.tilt if tilt is None else tilt) + dtilt))
            pixy.video_resume()
            # ramp in small steps: a sudden jump draws a current spike through the Pixy's USB
            # supply, which resets the Pixy (seen on the bench: USB device re-enumerated)
            while (self.pan, self.tilt) != (target_pan, target_tilt):
                self.pan += max(-SERVO_STEP, min(SERVO_STEP, target_pan - self.pan))
                self.tilt += max(-SERVO_STEP, min(SERVO_STEP, target_tilt - self.tilt))
                pixy.set_servos(self.tilt, self.pan)
                time.sleep(SERVO_STEP_DELAY)
            pixy.video_stop()
            save_servo(self.pan, self.tilt)
            return self.pan, self.tilt

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
        failures = 0
        while self._running:
            raw = self._grab()
            if raw is None:
                failures += 1
                if failures > MAX_GRAB_FAILURES:
                    # the Pixy reset (USB re-enumerated) and this handle is dead; exit so the
                    # control script's respawn loop starts a fresh process that reconnects
                    print("Pixy stopped answering; exiting for a clean restart", flush=True)
                    os._exit(3)
                time.sleep(0.05)
                continue
            failures = 0
            # focus score: variance of the Laplacian over the central area, measured before any
            # sharpening so it reflects the lens, smoothed so it doesn't jump around
            gray = cv2.cvtColor(raw, cv2.COLOR_BayerRG2GRAY)[H // 4 : 3 * H // 4, W // 4 : 3 * W // 4]
            score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            self.focus = score if self.focus is None else 0.7 * self.focus + 0.3 * score
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
            elif url.path == "/focus":
                self._send(f"{cam.focus or 0:.0f}".encode(), "text/plain")
            elif url.path == "/snapshot.jpg":
                self._send(cam.wait_frame() or b"", "image/jpeg")
            elif url.path == "/set":
                q = parse_qs(url.query)
                value = int(q["brightness"][0]) if "brightness" in q else None
                if value is not None:
                    value = max(0, min(255, value))
                self._send(f"brightness={cam.brightness(value)}".encode(), "text/plain")
            elif url.path == "/servo":
                q = parse_qs(url.query)

                def arg(k, default=None):
                    return int(q[k][0]) if k in q else default

                if any(k in q for k in ("pan", "tilt", "dpan", "dtilt")):
                    pan, tilt = cam.servo(arg("pan"), arg("tilt"), arg("dpan", 0), arg("dtilt", 0))
                else:
                    pan, tilt = cam.pan, cam.tilt
                self._send(f"pan={pan} tilt={tilt}".encode(), "text/plain")
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
