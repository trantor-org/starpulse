# CI shards the suite by test file (ci/shard.py); with SHARD_INDEX unset every test runs. In the nightly (TEST_COST_REPORT=1)
# a test over 5 s is named at the end of the run (ci/slow_tests.py). On a host with a `tests.slice` cgroup the run moves into it (ci/tests_slice.py).
pytest_plugins = ["shard", "slow_tests", "tests_slice"]
