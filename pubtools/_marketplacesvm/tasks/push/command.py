# SPDX-License-Identifier: GPL-3.0-or-later
import logging

from ...arguments import SplitAndExtend
from ...task import MarketplacesVMTask

LOG = logging.getLogger("pubtools.marketplacesvm")


class MarketplacesVMPush(MarketplacesVMTask):
    """Push and publish content to various cloud marketplaces."""

    def add_args(self):
        """Include the required CLI arguments for MarketplacesVMPush."""
        super(MarketplacesVMPush, self).add_args()

        self.add_publisher_args(self.parser)

        self.parser.add_argument(
            "--skip",
            help="skip given comma-separated sub-steps",
            type=str,
            action=SplitAndExtend,
            split_on=",",
            default=[],
        )

        self.parser.add_argument(
            "--pre-push",
            "--nochannel",
            action="store_true",
            dest="pre-push",
            help=(
                "Pre-push mode: do as much as possible without making content "
                "available to end-users, then stop. May be used to improve the "
                "performance of a subsequent full push."
            ),
        )

        self.parser.add_argument(
            "--source", action="append", help="Source(s) of content to be pushed"
        )

    def run(self):
        """Execute the push command workflow."""
        # Push workflow.
        # TODO: Implement the whole workflow as described below:
        #
        # 1. Collect the VMIPushItems from source
        # 2. Call StArMap for each VMIPushItems to retrieve the destinations
        # 3. Call the proper marketplace upload routine using `cloudimg`
        # 4. Execute the post upload routines depending on marketplace (scan image, export sas, etc)
        # 4.1 If "pre-push" (nochannel) is set then terminate the flow, otherwise continue
        # 5. Associate the VMI with the respective product listing and publish it using `cloudpub`
        #
        # It's posssible to implement the steps below either sequentially or using multithread like
        # pubtools-pulp does for multi-phases:
        #  https://github.com/release-engineering/pubtools-pulp/blob/master/pubtools/_pulp/tasks/push/command.py#L80
        #
        # Anyway we will need to have specific "phase providers" for each item from 3 to 5
        raise NotImplementedError("Need to implement this")
