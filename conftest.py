# CI shards the suite by test file (ci/shard.py); with SHARD_INDEX unset every test runs. Outside the nightly a test over 5 s
# fails unless exempt; in the nightly (TEST_COST_REPORT=1) it is named at the end of the run (ci/slow_tests.py). On a host with a `tests.slice` cgroup the run moves into it (ci/tests_slice.py).
# The servers of tests/integration/cli/test_agent_cli.py are built once per module run, not per case (ci/shared_servers.py).
pytest_plugins = ["shard", "slow_tests", "tests_slice", "shared_servers"]
