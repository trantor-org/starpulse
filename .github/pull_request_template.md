<!-- The title becomes the commit on main and the line in the release notes: write it for someone who uses StarPulse. Under "### References", add "Closes #<N>" for each GitHub issue this PR closes. This template is the workspace base (trantor .github/pull_request_template.md) verbatim below this comment; edit the base there, never here. -->

## Summary

<!-- Agent: Terse, concrete, skimmable. Structure comes from headings: every "### " below is its own subsection, never a "**Label:**" line. Keep paragraphs to two or three sentences, use bullets for three or more parallel items, and a table only to compare values. Use **bold** only for the numbers that matter.
Under "## Summary" itself: one bold line saying what changes once this merges, naming the component, inside a "> [!NOTE]" callout ("> [!NOTE]" on its own line, then "> **<line>**"). Callouts are for that line, Decide and a real Risk only; never elsewhere. -->
[Agent Summary Here]

### Background

<!-- Agent: Never drop this subsection. A refresher for a reader who has forgotten, or never knew, the task's history: what the affected system does, how it got to its current state, and what problem that left. Two to four short paragraphs or bullets, in plain sentences. Keep the precise terms, but gloss each piece of jargon, internal name or acronym on first use, in parentheses ("the reconciler (the hourly job that marks a task Done once its PR merges)") or as a link to where it is defined (an ADR, doc or upstream page). Assume the reader wants to learn the mechanism, not just approve the diff.
Then collect every glossed term in a closed drawer: "<details>", "<summary><b>Terms in this PR</b></summary>", a blank line, a "| Term | Meaning |" table with one row per term (one plain sentence, or a link to its definition), a blank line, "</details>". No jargon: drop the drawer, keep the subsection. -->

### Why

<!-- Agent: One real case with its names and numbers (the task's own figures), never a generic retelling. -->

### What changes

<!-- Agent: At most one ```diff snippet (≤10 lines) of the hunk that changes behavior, so the reader sees the change, not a paraphrase. Never a comment, docstring or test hunk; prose an agent or person follows (a skill, runbook or template) is behavior. No such hunk: drop this subsection. -->

### References

<!-- Agent: One bullet each for the linked task, spec, milestone and ADR. -->

## For the reviewer

### Decide

<!-- Agent: One concrete question only the reviewer can answer, in a callout: "> [!IMPORTANT]" on its own line, then "> <question>". Nothing to decide: drop this subsection. -->

### Check

<!-- Agent: The hunk worth reading closely, or "Nothing unusual." -->
[Impact Analysis Here]

### Risk

<!-- Agent: What runs on merge and what could break, in a "> [!WARNING]" callout ("> [!CAUTION]" when it touches live state or data and is hard to undo). No risk: the plain line "None.", never a callout. -->

## Verification

<!-- Agent: A "| | Check | Result |" table, one row per check: ✅ or ❌, the `command`, its result in a few words. Put long output in a "<details><summary>…</summary>" drawer below the table, never in a cell. List what you could not verify under a "### Not verified" subsection. Add a "## Changes" section above this one only when the change holds more than the Summary snippet shows: one bullet per behavior change, grouped under a "### " subsection per component when it spans more than one, never restating the Summary. -->
[Agent Verification Steps Here]
