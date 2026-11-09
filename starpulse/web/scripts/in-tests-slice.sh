#!/bin/sh
# Run a command inside the host's `tests.slice` cgroup when it has one, else run it in place.
#
# A host that budgets test CPU declares a systemd slice named tests.slice and lets its test users start transient
# tests-*.scope units. This script asks systemd to put its own process in such a scope, then execs the command, so the
# command and everything it forks run in the slice; systemd moves the process after the call returns, so it waits (up to
# 2 s) for the move before the command starts. A host without the slice or without busctl runs the command
# untouched; a host whose systemd refuses the scope prints one warning and does too. ci/tests_slice.py does the same for pytest.
#
#   in-tests-slice.sh vitest run
root=${CGROUP_ROOT:-/sys/fs/cgroup}
self=${SELF_CGROUP:-/proc/self/cgroup}
if command -v busctl >/dev/null 2>&1 && [ -d "$root/tests.slice" ] && ! grep -q '/tests.slice/' "$self"; then
  if err=$(busctl call org.freedesktop.systemd1 /org/freedesktop/systemd1 org.freedesktop.systemd1.Manager \
    StartTransientUnit 'ssa(sv)a(sa(sv))' "tests-vitest-$$.scope" fail 2 PIDs au 1 "$$" Slice s tests.slice 0 2>&1 >/dev/null); then
    tries=0
    while [ "$tries" -lt 20 ] && ! grep -q '/tests.slice/' "$self"; do
      sleep 0.1
      tries=$((tries + 1))
    done
  else
    echo "warning: not entering tests.slice: $err" >&2
  fi
fi
exec "$@"
