"""What one entry of a task's `documentation` list may be. It imports no model library, so the board's own writer
holds an internal caller to the rule the request models hold an HTTP client to."""

#: One entry as a JSON schema pattern: text that opens no JSON object or array.
PATTERN = r"^\s*([^\s\[{]|$)"


def doc_link(entry: str) -> str:
    """`entry` stripped, or ValueError when it is a JSON object or array: a command's reply passed for its doc id."""
    if (link := entry.strip()).startswith(("{", "[")):
        raise ValueError(f"documentation entry {link!r} is a JSON reply, not a link; pass its doc id (doc-N) instead")
    return link
