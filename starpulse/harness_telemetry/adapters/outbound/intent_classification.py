"""The intent label of a human prompt, from the instance's configured typed-decision endpoint.

The prompt text leaves StarPulse in the request and only the label comes back; neither is stored here. The call never
raises and never waits past the labeller's `timeout`: an endpoint that is down, slow or answers nothing usable leaves
the label empty, so ingest goes on without it.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx2

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
    body = {"state": text, "questions": _question(labeller), "model": labeller.model}
    try:
        response = httpx2.post(labeller.url, json=body, timeout=labeller.timeout)
        response.raise_for_status()
        choice = response.json()["answers"]["intent"]["choice"]
    except (httpx2.HTTPError, ValueError, KeyError, TypeError) as exc:
        log.warning("prompt labeller unavailable (%s); the prompt is left unlabelled", exc)
        return ""
    return choice if isinstance(choice, str) and choice in labeller.criteria else UNSURE
