#!/bin/bash
# Control the LMS services on the Pi. Run ON the Pi:
#   ~/lms-rover/infra/pi/lms-pi.sh install          copy units to systemd (once, after each deploy)
#   ~/lms-rover/infra/pi/lms-pi.sh start rover      start one: rover | sensehat | uno | pixy
#   ~/lms-rover/infra/pi/lms-pi.sh enable rover     start it at every boot too
#   ~/lms-rover/infra/pi/lms-pi.sh stop all         stop everything
#   ~/lms-rover/infra/pi/lms-pi.sh status           what is running
#   ~/lms-rover/infra/pi/lms-pi.sh logs rover       follow a service's log (Ctrl+C to leave)
# rover and pixy cannot run together (both need the Pixy camera); starting one stops the other.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
declare -A UNIT=([rover]=lms-rover [sensehat]=lms-sensehat [uno]=lms-uno-bridge [pixy]=lms-pixy-stream)
ALL="rover sensehat uno pixy"

units() {
  local which="${1:-all}"
  if [ "$which" = all ]; then for k in $ALL; do echo "${UNIT[$k]}"; done
  elif [ -n "${UNIT[$which]}" ]; then echo "${UNIT[$which]}"
  else echo "unknown service '$which' (use: $ALL all)" >&2; exit 1; fi
}

case "$1" in
  install)
    for k in $ALL; do sudo install -m 644 "$DIR/${UNIT[$k]}.service" /etc/systemd/system/; done
    sudo systemctl daemon-reload
    echo "installed: $(for k in $ALL; do printf '%s ' "${UNIT[$k]}"; done)" ;;
  start|stop|restart|enable|disable)
    for u in $(units "$2"); do
      if [ "$1" = enable ]; then sudo systemctl enable --now "$u"; else sudo systemctl "$1" "$u"; fi
    done ;;
  status)
    for k in $ALL; do printf '%-9s %s\n' "$k" "$(systemctl is-active "${UNIT[$k]}" 2>/dev/null)"; done ;;
  logs)
    journalctl -u "$(units "${2:-rover}")" -f -n 50 ;;
  *)
    sed -n '2,10p' "$0"; exit 1 ;;
esac
