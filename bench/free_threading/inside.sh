#!/bin/sh
# One measured run inside the image: copy the read-only state, serve it on one interpreter, warm it, then load it.
# Usage: inside.sh <gil|ft> <duration> <name>; /state is the state directory, /out the results directory.
# SERVER_CPUS and CLIENT_CPUS split the container's cpuset between the server and Locust; USERS is the crowd.
set -eu
venv=/opt/$1 duration=$2 out=/out/$3
cp -a /state /tmp/work
cd /tmp/work
cat /proc/loadavg >"$out.load"
taskset -c "$SERVER_CPUS" "$venv/bin/python" /src/bench/free_threading/serve.py \
  --config starpulse.toml --host 127.0.0.1 --port 8766 --hours 6 >"$out.server.log" 2>&1 &
server=$!
SERVER=$server /opt/gil/bin/python - <<'EOF'
import os, time, urllib.request
for _ in range(600):
    try:
        urllib.request.urlopen("http://127.0.0.1:8766/api/snapshot", timeout=30).read()
        break
    except OSError:
        os.kill(int(os.environ["SERVER"]), 0)  # raises once the server has exited
        time.sleep(1)
else:
    raise SystemExit("server never answered /api/snapshot")
EOF
locust() {
  taskset -c "$CLIENT_CPUS" /opt/gil/bin/locust -f /src/bench/load.py --host http://127.0.0.1:8766 --headless \
    --only-summary -u "$USERS" -r 5 "$@" || true
}
locust -t 1m >/dev/null 2>&1
locust -t "$duration" --csv "$out" >"$out.locust.log" 2>&1
cat /proc/loadavg >>"$out.load"
kill "$server"
wait "$server" || true
