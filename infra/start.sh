#!/bin/bash
# Start LMS backend services in WSL.  wsl -d Ubuntu-24.04 -u root -e bash /mnt/d/Project/LMS/infra/start.sh
set -u
for s in postgresql redis-server mosquitto; do
  service "$s" start > /dev/null 2>&1 || service "$s" restart > /dev/null 2>&1
  if service "$s" status > /dev/null 2>&1; then echo "$s: running"; else echo "$s: FAILED"; fi
done
