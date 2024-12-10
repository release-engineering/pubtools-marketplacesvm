# SPDX-License-Identifier: GPL-3.0-or-later
from pubtools._marketplacesvm.tasks.combined_push.command import CombinedVMPush


def entry_point(cls=CombinedVMPush):
    """Define the CLI entrypoint for the ``combined_push`` command."""
    cls().main()


def doc_parser():
    """Define the doc_parser for the ``combined_push`` command."""
    return CombinedVMPush().parser
