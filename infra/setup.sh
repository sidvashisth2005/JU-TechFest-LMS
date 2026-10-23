#!/bin/bash
# Configure LMS services in WSL after wsl_install.sh: DB user + schema, MQTT auth.
# Reads passwords from the repo's .env. Safe to run again.
# Run as root:  wsl -d Ubuntu-24.04 -u root -e bash /mnt/d/Project/LMS/infra/setup.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"

if [ ! -f "$ROOT/.env" ]; then
  echo "Missing $ROOT/.env — copy .env.example to .env and set passwords first." >&2
  exit 1
fi
set -a; source <(sed 's/\r$//' "$ROOT/.env"); set +a

# DATABASE_URL=postgresql://USER:PASS@HOST:PORT/DB
DB_USER=$(sed -E 's#.*://([^:]+):.*#\1#' <<< "$DATABASE_URL")
DB_PASS=$(sed -E 's#.*://[^:]+:([^@]+)@.*#\1#' <<< "$DATABASE_URL")
DB_NAME=$(sed -E 's#.*/([^/?]+)(\?.*)?$#\1#' <<< "$DATABASE_URL")

# ---------- PostgreSQL ----------
service postgresql start
sudo -u postgres psql -v ON_ERROR_STOP=1 -q <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
    CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASS}';
  ELSE
    ALTER ROLE ${DB_USER} PASSWORD '${DB_PASS}';
  END IF;
END \$\$;
SQL
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1 \
  || sudo -u postgres createdb -O "$DB_USER" "$DB_NAME"
# the extension must be created by a superuser
sudo -u postgres psql -q -d "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
sed 's/\r$//' "$HERE/schema.sql" | PGOPTIONS="-c client_min_messages=warning" PGPASSWORD="$DB_PASS" psql -q -o /dev/null -v ON_ERROR_STOP=1 -h localhost -U "$DB_USER" -d "$DB_NAME"
echo "PostgreSQL: database '$DB_NAME' ready for user '$DB_USER'"

# ---------- Mosquitto ----------
install -m 644 <(sed 's/\r$//' "$HERE/mosquitto.conf") /etc/mosquitto/conf.d/lms.conf
install -m 640 -o root -g mosquitto /dev/null /etc/mosquitto/lms_passwd.new
[ -f /etc/mosquitto/lms_passwd ] && cat /etc/mosquitto/lms_passwd > /etc/mosquitto/lms_passwd.new
mv /etc/mosquitto/lms_passwd.new /etc/mosquitto/lms_passwd
mosquitto_passwd -b /etc/mosquitto/lms_passwd "$MQTT_USER" "$MQTT_PASSWORD"
service mosquitto restart > /dev/null
echo "Mosquitto: user '$MQTT_USER' configured"

# ---------- Redis ----------
# default config (localhost only) is fine for the laptop
echo "Setup done. Start everything with infra/start.sh"
