"""The intent label of a human prompt, from the instance's configured typed-decision endpoint.

The prompt text leaves StarPulse in the request and only the label comes back; neither is stored here. The call never
raises and never waits past the labeller's `timeout`: an endpoint that is down, slow or answers nothing usable leaves
the label empty, so ingest goes on without it.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from starpulse.contracts.analytics import Labeller

__all__ = ["UNSURE", "intent_label"]

log = logging.getLogger(__name__)

#: The label for an answer that is none of the configured labels.
UNSURE = "unsure"


def _question(labeller: Labeller) -> dict[str, Any]:
    question: dict[str, Any] = {"type": "choice", "criteria": labeller.criteria}
    if labeller.instructions:
        question["instructions"] = labeller.instructions
    return {"intent": question}


def intent_label(labeller: Labeller, text: str) -> str:
    """The configured label the endpoint chose for `text`, `unsure` for any other choice, empty when it did not answer."""
    body = json.dumps({"state": text, "questions": _question(labeller), "model": labeller.model}).encode()
    request = urllib.request.Request(labeller.url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=labeller.timeout) as response:
            choice = json.loads(response.read())["answers"]["intent"]["choice"]
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as exc:
        log.warning("prompt labeller unavailable (%s); the prompt is left unlabelled", exc)
        return ""
    return choice if isinstance(choice, str) and choice in labeller.criteria else UNSURE
