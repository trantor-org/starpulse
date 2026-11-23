"""The Claude Code adapter of the Harness port."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from starpulse.harness_telemetry.model.harnesses import Tier


@dataclass(frozen=True)
class ClaudeHarness:
    tiers: Mapping[str, Tier] = field(default_factory=dict)
    name: str = "claude"
    skills_dir: str = ".claude/skills"
    events: Mapping[str, str] = field(
        default_factory=lambda: {
            "SessionStart": "SESSION_STARTED",
            "UserPromptSubmit": "SESSION_STARTED",
            "PostToolUse": "TOOL_USED",
            "Stop": "SESSION_STOPPED",
            "SessionEnd": "SESSION_ENDED",
            "user_prompt": "SESSION_STARTED",
            "skill_activated": "SKILL_USED",
            "tool_result": "TOOL_USED",
            "assistant_response": "SESSION_STOPPED",
            "settled": "SESSION_SETTLED",
        }
    )

    def launch(self, task: str, verb: str, profile: str | None) -> list[str]:
        agent = ["--agent", profile] if profile else []
        return ["claude", *agent, "--remote-control", task, f"{verb} {task}"]

    def model(self, tier: str, effort: str | None) -> str:
        return self.tiers[tier].model_for(effort)
