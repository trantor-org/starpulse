from seeded_server import budget_message


def test_an_over_budget_floor_message_names_the_host_load_per_cpu() -> None:
    message = budget_message({"snapshot": 114.0}, 1.5)

    assert "snapshot" in message
    assert "host load 1.50 per CPU" in message
