# CI shards the suite by test file (ci/shard.py); with SHARD_INDEX unset every test runs. A test over 5 s is named at
# the end of the run (ci/slow_tests.py).
pytest_plugins = ["shard", "slow_tests"]
