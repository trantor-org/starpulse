#!/bin/sh
# Interleaved A/B of StarPulse on CPython 3.14 (gil) and 3.14t (ft): each round runs both, alternating which goes first,
# with no network, on one cpuset. Usage: run.sh <state-dir> <out-dir> [rounds] [duration]
# Environment: CPUS (the container's cpuset, default 0-9), SERVER_CPUS (0-7), CLIENT_CPUS (8-9),
# USERS (the Locust crowd, 50), IMAGE (starpulse-free-threading).
set -eu
state=$(realpath "$1") out=$(realpath "$2") rounds=${3:-2} duration=${4:-3m}
image=${IMAGE:-starpulse-free-threading}
mkdir -p "$out"
round=1
while [ "$round" -le "$rounds" ]; do
  if [ $((round % 2)) -eq 1 ]; then order="gil ft"; else order="ft gil"; fi
  for interpreter in $order; do
    echo "round $round $interpreter"
    docker run --rm --network none --cpuset-cpus "${CPUS:-0-9}" \
      -e SERVER_CPUS="${SERVER_CPUS:-0-7}" -e CLIENT_CPUS="${CLIENT_CPUS:-8-9}" -e USERS="${USERS:-50}" \
      -v "$state:/state:ro" -v "$out:/out" -e HOME=/tmp --user "$(id -u):$(id -g)" \
      "$image" sh /src/bench/free_threading/inside.sh "$interpreter" "$duration" "$interpreter-$round"
  done
  round=$((round + 1))
done
python3 "$(dirname "$0")/summarize.py" "$out"
