#!/bin/bash
# Install the boot-time IP announcer + setup hotspot on a Pi. Run ON the Pi as root, with the
# hotspot password (8+ characters) on stdin:
#   echo 'the-password' | sudo bash ~/lms/infra/pi/install_boot_ip.sh
# From the laptop, infra/find_pi.py --install does this for you (password from the laptop .env).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }

install -D -m 755 "$DIR/lms_boot_ip.py" /usr/local/lib/lms/lms_boot_ip.py
install -m 644 "$DIR/lms-boot-ip.service" /etc/systemd/system/lms-boot-ip.service
sed -i 's/\r$//' /usr/local/lib/lms/lms_boot_ip.py /etc/systemd/system/lms-boot-ip.service

if [ ! -t 0 ]; then
  read -r PW || true
  if [ "${#PW}" -ge 8 ]; then
    install -d -m 700 /etc/lms
    umask 077
    printf 'password=%s\n' "$PW" > /etc/lms/ap.conf
    echo "hotspot password saved in /etc/lms/ap.conf"
  fi
fi
[ -f /etc/lms/ap.conf ] || echo "WARNING: no hotspot password set: the setup hotspot stays off"

systemctl daemon-reload
systemctl enable lms-boot-ip.service
echo "installed: lms-boot-ip runs at every boot (journalctl -u lms-boot-ip)"
