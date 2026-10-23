#!/bin/bash
# Start / stop / restart the Pixy2 MJPEG streamer in the background.
# Usage: ~/lms-tools/pixy_stream_ctl.sh start|stop|restart|status
#
# The streamer runs inside a respawn loop: if the Pixy resets (USB re-enumerates, e.g. when
# the pan-tilt servos draw a current spike) the streamer exits and is started again.
PAT="^$HOME/lms-venv/bin/python -u $HOME/lms-tools/pixy_stream.py"
LOG=/tmp/pixy_stream.log
LOOP_PID=/tmp/pixy_stream_loop.pid

stop() {
  if [ -f "$LOOP_PID" ]; then
    kill "$(cat "$LOOP_PID")" 2>/dev/null
    rm -f "$LOOP_PID"
  fi
  pkill -TERM -f "$PAT" && sleep 3
  pkill -KILL -f "$PAT" && sleep 2
  true
}

start() {
  local args="$*"
  setsid nohup bash -c "
    while true; do
      $HOME/lms-venv/bin/python -u $HOME/lms-tools/pixy_stream.py $args
      echo \"\$(date '+%H:%M:%S') streamer exited (\$?), restarting in 2 s\"
      sleep 2
    done" > "$LOG" 2>&1 < /dev/null &
  echo $! > "$LOOP_PID"
  sleep 6
  head -3 "$LOG"
}

case "$1" in
  start)   shift; start "$@" ;;
  stop)    stop ;;
  restart) shift; stop; start "$@" ;;
  status)  pgrep -af "$PAT" || echo "not running" ;;
  *)       echo "usage: $0 start|stop|restart|status [streamer args]"; exit 1 ;;
esac
