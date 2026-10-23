#!/bin/bash
# One-time install of LMS backend services inside WSL Ubuntu 24.04 (no Docker).
# Run as root:  wsl -d Ubuntu-24.04 -u root -e bash /mnt/d/Project/LMS/infra/wsl_install.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y curl gnupg lsb-release ca-certificates mosquitto mosquitto-clients redis-server \
  postgresql-16 postgresql-contrib

# TimescaleDB from the official packagecloud repo
CODENAME=$(lsb_release -cs)
if [ ! -f /etc/apt/sources.list.d/timescaledb.list ]; then
  curl -fsSL https://packagecloud.io/timescale/timescaledb/gpgkey | gpg --dearmor -o /etc/apt/trusted.gpg.d/timescaledb.gpg
  echo "deb https://packagecloud.io/timescale/timescaledb/ubuntu/ ${CODENAME} main" > /etc/apt/sources.list.d/timescaledb.list
  apt-get update
fi
apt-get install -y timescaledb-2-postgresql-16
timescaledb-tune --quiet --yes --pg-config=/usr/lib/postgresql/16/bin/pg_config

echo "Install done. Next: infra/setup.sh to create users, DB and MQTT config."
