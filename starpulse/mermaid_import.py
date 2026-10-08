"""Drafting a machine definition from a Mermaid state diagram, `python -m starpulse.mermaid_import flow.mmd`; the implementation is in `starpulse.domain.mermaid_import`."""

from starpulse.domain.mermaid_import import Diagram, Edge, draft_machine, dump, main, parse

__all__ = ["Diagram", "Edge", "draft_machine", "dump", "parse"]

if __name__ == "__main__":
    main()
