# SPDX-License-Identifier: GPL-3.0-or-later
from .command import VMDelete


def entry_point(cls=VMDelete):
    """Define the CLI entrypoint for the ``delete`` command."""
    cls().main()


def doc_parser():
    """Define the doc_parser for the ``delete`` command."""
    return VMDelete().parser
