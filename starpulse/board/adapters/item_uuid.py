"""The UUID every board item stores beside its key: a v7 minted at create. A Task that existed before a UUID was stored
has the v5 of its board and key, which revision 0074 stamps into its History."""

import uuid


def mint() -> str:
    return str(uuid.uuid7())
