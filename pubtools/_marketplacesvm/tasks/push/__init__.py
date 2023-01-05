# SPDX-License-Identifier: GPL-3.0-or-later
from .command import MarketplacesVMPush


def entry_point(cls=MarketplacesVMPush):
    with cls() as instance:
        instance.main()


def doc_parser():
    return MarketplacesVMPush().parser
