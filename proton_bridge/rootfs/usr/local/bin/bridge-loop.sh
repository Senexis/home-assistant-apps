#!/bin/bash
while true; do
  /usr/local/bin/bridge --cli
  echo "Bridge exited, restarting in 5 seconds..."
  sleep 5
done
