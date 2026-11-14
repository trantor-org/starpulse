"""Outbound runs adapters, one module per scheduler."""


class Unreported:
    """A runs sink that drops what it is given, for a one-off read that reports nowhere."""

    def set_dags(self, *args: object) -> None:
        return
