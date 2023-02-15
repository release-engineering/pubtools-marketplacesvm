# SPDX-License-Identifier: GPL-3.0-or-later
from .command import MarketplacesVMPush


def entry_point(cls=MarketplacesVMPush):
    """Define the CLI entrypoint for the ``push`` command."""
    cls().main()


def doc_parser():
    """Define the doc_parser for the ``push`` command."""
    return MarketplacesVMPush().parser
