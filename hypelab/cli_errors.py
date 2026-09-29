"""Shared CLI failure type (T-003: BUG-001).

Deterministic CLI failures (bad input, missing resources, failed
preconditions) raise :class:`CliError` -- a plain :class:`Exception` --
instead of killing the process with ``SystemExit``.  Normal
``except Exception`` guards (notably the ``work`` claim-loop in
``hypelab/cli.py``) then record the failure and keep the worker alive,
while the Click entrypoint (:class:`CliGroup`) translates a CliError
that reaches the CLI boundary into the historical behavior: the message
on stderr and a nonzero process exit.
"""
from __future__ import annotations

import click


class CliError(Exception):
    """Deterministic CLI failure.

    Carries the message ``_die`` already printed and the exit code the
    CLI boundary should use.  A regular ``Exception`` subclass on
    purpose: ``SystemExit`` (a ``BaseException``) escapes
    ``except Exception`` guards and kills long-lived workers.
    """

    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.msg = msg
        self.code = code


class CliGroup(click.Group):
    """Click group that scopes the process exit to the CLI boundary.

    ``_die()`` prints ``error: <msg>`` itself and raises
    :class:`CliError`; the group converts it to ``ctx.exit(code)`` so
    one-shot commands keep their clean stderr + nonzero-exit contract,
    while in-process callers (worker loops, tests) can catch CliError
    as a normal exception.
    """

    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except CliError as e:
            ctx.exit(e.code)
