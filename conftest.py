# CI shards the suite by test file (ci/shard.py); with SHARD_INDEX unset every test runs.
pytest_plugins = ["shard"]
