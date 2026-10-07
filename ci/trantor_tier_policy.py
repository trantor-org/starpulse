"""Run trantor's test-tier policy over this repository and fail on any violation.

trantor pins starpulse and its `check-config` fails a pin whose tree breaks the policy, such as a unit test that starts
an HTTP server. Running it here keeps such a commit from going green, so trantor's bump never pins one. The module is
loaded by path, not imported through its package, so only `pyyaml` and trantor's `lib/` are needed.

Usage: PYTHONPATH=<trantor>/lib python ci/trantor_tier_policy.py <trantor>/lib/linting/check_config_checks/tier_policy.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def main(policy: str) -> int:
    spec = importlib.util.spec_from_file_location("tier_policy", policy)
    assert spec and spec.loader, policy
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    violations = module.tier_violations(Path(__file__).resolve().parents[1], root=False)
    for violation in violations:
        print(f"::error::{violation}")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
