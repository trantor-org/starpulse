"""The step times of the agent's commands.

- `POST /api/steps`: the seconds each step of one gate or fixed-cost command run took and its reuse hit or miss, observed in
  Prometheus (`agent_step_seconds`, `agent_reuse_total`); the answer is `{"accepted": true}`.
"""

from starlette.requests import Request

from starpulse.contracts.api.dto.requests import StepsRequest
from starpulse.views.adapters.inbound.api.answering import client
from starpulse.views.adapters.inbound.api.table import ApiRoute, WriteRoute
from starpulse.views.adapters.inbound.api.writing import guarded, whole
from starpulse.views.adapters.outbound import agent_steps
from starpulse.views.application.commands.guard import with_request


@with_request(StepsRequest, "Recording step times")
def record(steps: StepsRequest) -> tuple[int, dict]:
    agent_steps.observe(steps)
    return 200, {"accepted": True}


def _write(request: Request) -> tuple[int, dict]:
    return record(client(request), whole(request))


routes: list[ApiRoute] = [WriteRoute("/steps", ("POST",), guarded("ingest", _write))]
