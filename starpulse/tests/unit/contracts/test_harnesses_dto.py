"""`/api/harnesses` body: a tier with a `run_efforts` table is served, not refused."""

from starpulse.contracts.api.dto.harnesses import HarnessTier


def test_a_tier_with_run_efforts_validates() -> None:
    tier = HarnessTier.model_validate(
        {"model": "sonnet", "efforts": ["low", "high"], "run_efforts": {"low": "medium", "high": "medium"}}
    )

    assert tier.run_efforts == {"low": "medium", "high": "medium"}
