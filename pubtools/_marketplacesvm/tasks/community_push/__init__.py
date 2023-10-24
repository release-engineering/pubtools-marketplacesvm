# SPDX-License-Identifier: GPL-3.0-or-later
from .command import CommunityVMPush


def entry_point(cls=CommunityVMPush):
    """Define the CLI entrypoint for the ``community_push`` command."""
    cls().main()


def doc_parser():
    """Define the doc_parser for the ``community_push`` command."""
    return CommunityVMPush().parser
