#!/bin/bash
# Copy the current code to the Pi and install its services. Run on the LAPTOP (Git Bash),
# from the repo root:
#   bash infra/pi/deploy.sh                 uses PI=pi@10.77.218.209
#   PI=pi@192.168.1.50 bash infra/pi/deploy.sh
# The repo is private, so the Pi never needs GitHub access: the committed tree (HEAD) is
# streamed over SSH. Commit first if you want local edits included.
set -euo pipefail
PI="${PI:-pi@10.77.218.209}"
cd "$(dirname "$0")/../.."
echo "== copying $(git rev-parse --short HEAD) to $PI:~/lms-rover"
ssh -o BatchMode=yes "$PI" 'mkdir -p ~/lms-rover'
git archive --format=tar HEAD | ssh -o BatchMode=yes "$PI" 'tar -x -C ~/lms-rover'
echo "== python packages"
ssh -o BatchMode=yes "$PI" '~/lms-venv/bin/pip install -q -r ~/lms-rover/rover/requirements.txt python-dotenv'
echo "== Pi .env"
if ssh -o BatchMode=yes "$PI" 'test -f ~/lms-rover/.env'; then
  echo "kept the existing ~/lms-rover/.env on the Pi"
else
  # first deploy: fill the secrets from the laptop .env and the laptop's Wi-Fi IP
  get() { grep -E "^$1=" .env | head -1 | cut -d= -f2-; }
  LAPTOP_IP="${LAPTOP_IP:-$(powershell -NoProfile -Command "(Get-NetIPAddress -InterfaceAlias Wi-Fi -AddressFamily IPv4).IPAddress" 2>/dev/null | tr -d '\r')}"
  sed -e "s|^MQTT_HOST=.*|MQTT_HOST=${LAPTOP_IP}|" \
      -e "s|^MQTT_USER=.*|MQTT_USER=$(get MQTT_USER)|" \
      -e "s|^MQTT_PASSWORD=.*|MQTT_PASSWORD=$(get MQTT_PASSWORD)|" \
      -e "s|^ROVER_TOKEN=.*|ROVER_TOKEN=$(get ROVER_TOKEN)|" infra/pi/pi.env.example \
    | ssh -o BatchMode=yes "$PI" 'cat > ~/lms-rover/.env && chmod 600 ~/lms-rover/.env'
  echo "created ~/lms-rover/.env on the Pi (MQTT_HOST=$LAPTOP_IP, secrets copied from the laptop .env)"
fi
echo "== services"
ssh -o BatchMode=yes "$PI" 'cd ~/lms-rover && sed -i "s/\r$//" infra/pi/*.sh && chmod +x infra/pi/*.sh &&
  infra/pi/lms-pi.sh install && infra/pi/lms-pi.sh status'
echo "== done. Start the rover:  ssh $PI '~/lms-rover/infra/pi/lms-pi.sh start rover'"
