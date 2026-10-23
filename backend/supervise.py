"""Keep one worker running: restart it whenever it exits, with backoff.

    python -m backend.supervise ingest -- -m backend.workers.ingest

Everything after `--` is passed to this same Python interpreter. Output goes to
logs/<name>.log (appended), including a line for every restart. A child that ran for a
while resets the backoff, so a one-off crash restarts in 2 s but a crash loop slows to 60 s.
"""

import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    if "--" not in sys.argv or sys.argv.index("--") != 2:
        sys.exit("usage: python -m backend.supervise NAME -- <python args>")
    name, child_args = sys.argv[1], sys.argv[3:]
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    log = open(logs / f"{name}.log", "a", buffering=1, encoding="utf-8")
    stopping = False
    proc = None

    def stop(*_):
        nonlocal stopping
        stopping = True
        if proc and proc.poll() is None:
            proc.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    delay = 2.0
    while not stopping:
        started = time.time()
        log.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} supervise: starting {name}\n")
        proc = subprocess.Popen([sys.executable, *child_args], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        code = proc.wait()
        if stopping:
            break
        delay = 2.0 if time.time() - started > 60 else min(delay * 2, 60)
        log.write(f"--- {time.strftime('%H:%M:%S')} supervise: {name} exited with {code}; restart in {delay:.0f}s\n")
        time.sleep(delay)


if __name__ == "__main__":
    main()
