#!/bin/bash
# Install the IP beacon as a user service (starts at boot, no login, no sudo). Run ON the Pi:
#   bash infra/pi/install_beacon.sh <role>        role = rover | barn
# Settings come from stdin as KEY=VALUE lines (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) and are kept
# in ~/.config/lms/beacon.env (mode 600). infra/find_pi.py --install runs this for you.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
ROLE="${1:-}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

install -D -m 755 "$DIR/lms_beacon.py" ~/.local/lib/lms/lms_beacon.py
install -D -m 644 "$DIR/lms-beacon.service" ~/.config/systemd/user/lms-beacon.service
sed -i 's/\r$//' ~/.local/lib/lms/lms_beacon.py ~/.config/systemd/user/lms-beacon.service

mkdir -p ~/.config/lms
umask 077
{
  echo "LMS_ROLE=$ROLE"
  if [ ! -t 0 ]; then grep -E '^(TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID)=' || true; fi
} > ~/.config/lms/beacon.env

loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable lms-beacon.service
systemctl --user restart lms-beacon.service
sync  # survive a power cut right after installing (unsynced files come back empty)
echo "lms-beacon: $(systemctl --user is-active lms-beacon), boot: $(systemctl --user is-enabled lms-beacon)"
