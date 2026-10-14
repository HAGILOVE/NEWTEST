"""Cooperative cancellation at solver stage boundaries."""


class SolveCancelled(RuntimeError):
    pass


def checkpoint(cancel=None):
    if cancel is not None and cancel.is_set():
        raise SolveCancelled("Cancelled at a solver checkpoint")
