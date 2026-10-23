#!/bin/bash
# Start / stop / restart the Pixy2 MJPEG streamer in the background.
# Usage: ~/lms-tools/pixy_stream_ctl.sh start|stop|restart|status
PAT="^$HOME/lms-venv/bin/python -u $HOME/lms-tools/pixy_stream.py"
LOG=/tmp/pixy_stream.log

stop() {
  pkill -TERM -f "$PAT" && sleep 3
  pkill -KILL -f "$PAT" && sleep 2
  true
}

start() {
  setsid nohup "$HOME/lms-venv/bin/python" -u "$HOME/lms-tools/pixy_stream.py" "$@" > "$LOG" 2>&1 < /dev/null &
  sleep 6
  cat "$LOG"
}

case "$1" in
  start)   shift; start "$@" ;;
  stop)    stop ;;
  restart) shift; stop; start "$@" ;;
  status)  pgrep -af "$PAT" || echo "not running" ;;
  *)       echo "usage: $0 start|stop|restart|status [streamer args]"; exit 1 ;;
esac
