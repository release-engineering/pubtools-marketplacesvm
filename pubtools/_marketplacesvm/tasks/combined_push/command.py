# SPDX-License-Identifier: GPL-3.0-or-later
import json
import logging
from typing import Any, Dict, List

from more_executors import Executors

from ...arguments import SplitAndExtend
from ...services import CloudService, StarmapService
from ...services.rhsm import AwsRHSMClientService
from ...task import RUN_RESULT, MarketplacesVMTask
from ..community_push import CommunityVMPush
from ..push import MarketplacesVMPush

log = logging.getLogger("pubtools.marketplacesvm")


class CombinedVMPush(MarketplacesVMTask, CloudService, StarmapService, AwsRHSMClientService):
    """Combine the Marketplace and Community pushes into a single entity."""

    _REQUEST_THREADS = 2

    def __init__(self, *args, **kwargs):
        """Initialize the CombinedVMPush instance."""
        self._community_push = CommunityVMPush()
        self._marketplace_push = MarketplacesVMPush()
        super(CombinedVMPush, self).__init__(*args, **kwargs)
        self._community_push.parser = self.parser
        self._marketplace_push.parser = self.parser

    def add_args(self):
        """Include the required CLI arguments for CommunityVMPush and MarketplacesVMPush."""
        super(CombinedVMPush, self).add_args()

        marketplace = self.parser.add_argument_group("Marketplace Push Options")
        marketplace.add_argument(
            "--skip",
            help="skip given comma-separated sub-steps",
            type=str,
            action=SplitAndExtend,
            split_on=",",
            default=[],
        )

        marketplace.add_argument(
            "--pre-push",
            action="store_true",
            help=(
                "Pre-push mode: do as much as possible without making content "
                "available to end-users, then stop. May be used to improve the "
                "performance of a subsequent full push."
            ),
        )

        marketplace.add_argument(
            "--repo",
            help="Override the destinations of a cloud marketplace account for all push items. "
            "e.g: {'aws-na': [{'destination': 'c39fd...', overwrite: true}, ...]}",
            type=json.loads,
            default={},
        )

        marketplace.add_argument(
            "source",
            nargs="+",
            help="Source(s) of content to be pushed",
            action=SplitAndExtend,
            split_on=",",
        )

        community = self.parser.add_argument_group("Community Push options")

        community.add_argument(
            "--beta",
            help="Ship beta images instead of GA",
            action="store_true",
        )

        community.add_argument(
            "--container-prefix",
            help="prefix to storage container for uploading community images",
            default="redhat-cloudimg",
        )

        workflow = self.parser.add_argument_group("Workflow options")

        workflow.add_argument(
            "--workflow",
            "-w",
            choices=['marketplace', 'community', 'all'],
            default='all',
            help="The workflow to be executed",
        )

    @staticmethod
    def _evaluate_push_results(
        push_results: List[RUN_RESULT], collected_data: List[Dict[str, Any]]
    ) -> RUN_RESULT:
        workflow1 = push_results.pop()
        workflow2 = push_results.pop()

        # Failure condition 1: At least one workflow failed
        if not (workflow1.success and workflow2.success):
            log.info("Combined VM push failed: at least one workflow failed.")
            return RUN_RESULT(False, False, collected_data)

        # Failure condition 2: Both workflows were empty
        if workflow1.skipped and workflow2.skipped:
            log.info("Combined VM push failed: both workflows were empty.")
            return RUN_RESULT(False, True, collected_data)

        # Success
        log.info("Combined VM push completed")
        return RUN_RESULT(True, (workflow1.skipped or workflow2.skipped), collected_data)

    def run(self, collect_results: bool = True, allow_empty_targets: bool = False) -> RUN_RESULT:
        """Execute the combined push command workflow."""
        # -- Individual workflow
        if self.args.workflow == "marketplace":
            return self._marketplace_push.run()

        elif self.args.workflow == "community":
            return self._community_push.run()

        # -- Combined workflow
        executor = Executors.thread_pool(
            name="pubtools-marketplacesvm-push-combined",
            max_workers=self._REQUEST_THREADS,
        )
        combined_kwargs = {
            "collect_results": False,
            "allow_empty_targets": True,
        }

        # Execute each workflow in parallel
        to_await = []
        for push in [self._marketplace_push, self._community_push]:
            to_await.append(executor.submit(push.run, **combined_kwargs))

        # Wait for results
        push_results: List[RUN_RESULT] = []
        for f_out in to_await:
            push_results.append(f_out.result())

        # Collect results
        log.info("Collecting results")
        data_to_collect = []
        for res in push_results:
            data_to_collect.extend(res.collected_result)
        # NOTE: The collect_push_result is the same function for both workflows
        # as CommunityVMPush inherits it from MarketplacesVMPush.
        self._marketplace_push.collect_push_result(data_to_collect)

        # Finish
        return self._evaluate_push_results(push_results, data_to_collect)
