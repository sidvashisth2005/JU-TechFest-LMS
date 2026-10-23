#!/bin/bash
# Control the barn station (Sense HAT -> MQTT) on the barn Pi. Run ON the Pi:
#   ~/lms/infra/pi/lms-barn.sh install     copy the unit to ~/.config/systemd/user (once, after each deploy)
#   ~/lms/infra/pi/lms-barn.sh on          autostart at every boot + start now
#   ~/lms/infra/pi/lms-barn.sh off         no autostart + stop now
#   ~/lms/infra/pi/lms-barn.sh toggle      on <-> off
#   ~/lms/infra/pi/lms-barn.sh start|stop|restart
#   ~/lms/infra/pi/lms-barn.sh status
#   ~/lms/infra/pi/lms-barn.sh logs        follow the log (Ctrl+C to leave)
# It is a systemd USER service with lingering on, so it starts at boot without anyone logging
# in and needs no sudo. Settings come from ~/lms/.env (MQTT_*, BARN_STATION, BARN_INTERVAL,
# BARN_LETTER, BARN_BRIGHT).
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
UNIT=lms-sensehat
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

install_unit() {
  mkdir -p ~/.config/systemd/user
  install -m 644 "$DIR/lms-sensehat-user.service" ~/.config/systemd/user/$UNIT.service
  loginctl enable-linger "$USER"
  systemctl --user daemon-reload
}

status() {
  printf 'sensehat  %s, boot: %s\n' "$(systemctl --user is-active $UNIT 2>/dev/null)" \
    "$(systemctl --user is-enabled $UNIT 2>/dev/null || true)"
}

case "$1" in
  install) install_unit; echo "installed $UNIT (user service)" ;;
  on)      install_unit; systemctl --user enable --now $UNIT; status ;;
  off)     systemctl --user disable --now $UNIT; status ;;
  toggle)
    if systemctl --user is-enabled -q $UNIT 2>/dev/null; then "$0" off; else "$0" on; fi ;;
  start|stop|restart) systemctl --user "$1" $UNIT; status ;;
  is-enabled) systemctl --user is-enabled $UNIT 2>/dev/null || true ;;
  status)  status ;;
  logs)    journalctl --user -u $UNIT -f -n 50 ;;
  *)       sed -n '2,11p' "$0"; exit 1 ;;
esac
