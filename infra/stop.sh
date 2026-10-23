#!/bin/bash
# Stop LMS backend services in WSL.
for s in mosquitto redis-server postgresql; do
  service "$s" stop > /dev/null 2>&1 && echo "$s: stopped"
done
