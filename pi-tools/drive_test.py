"""8-second BrickPi3 drive test: every motor action once, with the ultrasonic watching.

    ~/lms-venv/bin/python ~/lms-tools/drive_test.py            # tracks lifted first!
    ~/lms-venv/bin/python ~/lms-tools/drive_test.py --speed 200 --drive-sign -1
    ~/lms-venv/bin/python ~/lms-tools/drive_test.py --safety   # 5 s forward only: put a hand in front
    ~/lms-venv/bin/python ~/lms-tools/drive_test.py --no-ultrasonic   # motors only (tracks lifted!)

Sequence (8 s): forward 1.5 s, stop 0.5, backward 1.5, stop 0.5, turn left 1.5,
turn right 1.5, stop 1.0. The EV3 ultrasonic (S2) is read every 50 ms; while driving
forward, an obstacle closer than --stop-cm (or "no echo" right after a close reading,
which means too close, not clear) stops the motors. Ctrl+C stops everything.
Ports and signs match rover/config.py: left = D, right = C.
"""

import argparse
import time

import brickpi3

STEPS = [  # (name, left direction, right direction, seconds)
    ("forward", 1, 1, 1.5),
    ("stop", 0, 0, 0.5),
    ("backward", -1, -1, 1.5),
    ("stop", 0, 0, 0.5),
    ("turn left", -1, 1, 1.5),
    ("turn right", 1, -1, 1.5),
    ("stop", 0, 0, 1.0),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--speed", type=int, default=300, help="motor degrees/second (max ~900)")
    ap.add_argument("--left", default="D")
    ap.add_argument("--right", default="C")
    ap.add_argument("--drive-sign", type=int, choices=[-1, 1], default=1, help="-1 if forward drives backwards")
    ap.add_argument("--stop-cm", type=float, default=25)
    ap.add_argument("--safety", action="store_true", help="only drive forward for 5 s to test the obstacle stop")
    ap.add_argument("--no-ultrasonic", action="store_true", help="motors only, no obstacle stop (tracks lifted)")
    args = ap.parse_args()
    steps = [("forward", 1, 1, 5.0)] if args.safety else STEPS

    bp = brickpi3.BrickPi3()
    left, right = getattr(bp, "PORT_" + args.left), getattr(bp, "PORT_" + args.right)
    us = bp.PORT_2
    try:
        volts = bp.get_voltage_battery()
        print(f"battery {volts:.2f} V")
        if volts < 9.0:
            print("battery below 9 V - charge it first")
            return

        if args.no_ultrasonic and args.safety:
            print("--safety tests the ultrasonic; it cannot run with --no-ultrasonic")
            return
        if args.no_ultrasonic:
            print("ultrasonic OFF: no obstacle stop, keep the tracks lifted")
        else:
            bp.set_sensor_type(us, bp.SENSOR_TYPE.EV3_ULTRASONIC_CM)
            print("ultrasonic warming up (~3.5 s)...")
        t0 = time.time()
        while not args.no_ultrasonic:
            try:
                bp.get_sensor(us)
                break
            except brickpi3.SensorError:
                if time.time() - t0 > 8:
                    print("ultrasonic not answering on S2 - check the cable")
                    return
                time.sleep(0.1)

        print(f"{'action':<11} {'L enc':>7} {'R enc':>7} {'L dps':>6} {'R dps':>6}  ultrasonic cm (min..max)  note")
        last_close = 0.0
        for name, ldir, rdir, secs in steps:
            for p in (left, right):
                bp.offset_motor_encoder(p, bp.get_motor_encoder(p))
            sign = args.drive_sign
            bp.set_motor_dps(left, ldir * sign * args.speed)
            bp.set_motor_dps(right, rdir * sign * args.speed)
            dists, note, speeds, end = [], "", (0, 0), time.time() + secs
            while time.time() < end:
                try:
                    d = None if args.no_ultrasonic else bp.get_sensor(us)
                except brickpi3.SensorError:
                    d = None
                if d is not None and d < 255:
                    dists.append(d)
                    if d < args.stop_cm:
                        last_close = time.time()
                close = d is not None and (d < args.stop_cm or (d >= 255 and time.time() - last_close < 1.0))
                if name == "forward" and close and not note:
                    bp.set_motor_dps(left, 0)
                    bp.set_motor_dps(right, 0)
                    note = f"OBSTACLE - stopped at {d:.0f} cm" if d < 255 else "OBSTACLE - too close (no echo)"
                if not note and time.time() > end - secs / 2:  # mid-step speed sample
                    speeds = (bp.get_motor_status(left)[3], bp.get_motor_status(right)[3])
                time.sleep(0.05)
            le, re_ = bp.get_motor_encoder(left), bp.get_motor_encoder(right)
            if ldir and not note:
                expect = ldir * sign
                ok = (le * expect > 30) and (re_ * rdir * sign > 30)
                note = note or ("ok" if ok else "CHECK: a motor did not turn the expected way")
            rng = f"{min(dists):5.1f}..{max(dists):5.1f}" if dists else "  no echo   "
            print(f"{name:<11} {le:>7} {re_:>7} {speeds[0]:>6} {speeds[1]:>6}  {rng:<24} {note}")
        print("done")
    except KeyboardInterrupt:
        print("stopped by Ctrl+C")
    finally:
        bp.reset_all()


if __name__ == "__main__":
    main()
