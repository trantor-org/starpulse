#!/bin/sh
# Run the web checks (typecheck, lint, vitest, build) at once and fail when any does.
#
#   check.sh                       the whole suite and both builds: `pnpm run check`, the nightly job
#   check.sh --changed FILE...     the gate: FILE are the change's repo-root paths; vitest runs only the tests that
#                                  import a changed web source file (`vitest related` follows the import graph), the
#                                  whole suite when the change reaches config, lockfile, scripts or the page shell,
#                                  and no test when it touches nothing under starpulse/web; one build, the page
#   check.sh --plan ...            print the test and build choice and exit
mode=full
if [ "$1" = --plan ]; then plan=1; shift; fi
if [ "$1" = --changed ]; then mode=changed; shift; fi

tests=all
build="pnpm run build"
if [ "$mode" = changed ]; then
  build="pnpm exec vite build"
  tests=none
  related=
  for file in "$@"; do
    case $file in
      starpulse/web/src/*) tests=related; related="$related ${file#starpulse/web/}" ;;
      starpulse/web/*) tests=all; break ;;
      starpulse/schemas/api.schema.json) tests=all; break ;;
    esac
  done
fi

case $tests in
  all) test_cmd="scripts/in-tests-slice.sh pnpm exec vitest run" ;;
  related) test_cmd="scripts/in-tests-slice.sh pnpm exec vitest related --run$related" ;;
  none) test_cmd=true ;;
esac

if [ -n "$plan" ]; then
  if [ "$tests" = related ]; then echo "test: related$related"; else echo "test: $tests"; fi
  echo "build: $build"
  exit 0
fi

dir=$(mktemp -d) || exit 1
trap 'rm -rf "$dir"' EXIT
pids=
for name in typecheck lint test build; do
  case $name in
    typecheck) cmd="pnpm run typecheck" ;;
    lint) cmd="pnpm run lint" ;;
    test) cmd=$test_cmd ;;
    build) cmd=$build ;;
  esac
  (
    $cmd >"$dir/$name.log" 2>&1
    echo $? >"$dir/$name.status"
  ) &
  pids="$pids $!"
done
wait $pids

failed=0
for name in typecheck lint test build; do
  status=$(cat "$dir/$name.status")
  echo "=== $name: exit $status ==="
  cat "$dir/$name.log"
  if [ "$status" != 0 ]; then failed=1; fi
done
exit $failed
