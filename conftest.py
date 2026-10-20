# Outside the nightly a test over 5 s fails unless exempt; in the nightly (TEST_COST_REPORT=1) it is named at the end of
# the run (ci/slow_tests.py).
# The servers of starpulse/tests/integration/cli/test_agent_cli.py are built once per module run, not per case (ci/shared_servers.py).
pytest_plugins = ["slow_tests", "shared_servers"]
