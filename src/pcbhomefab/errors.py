"""Exceptions raised by pcbhomefab."""


class PCBHomeFabError(Exception):
    """Base class for all errors raised on purpose by the library."""


class InputError(PCBHomeFabError):
    """The uploaded data is invalid, unsupported or exceeds a limit. The message is safe to show to users."""


class LayoutError(PCBHomeFabError):
    """The boards do not fit on the blank with the given settings."""
