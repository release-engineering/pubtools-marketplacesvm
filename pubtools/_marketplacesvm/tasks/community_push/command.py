# SPDX-License-Identifier: GPL-3.0-or-later
import json
import logging
import os
import sys
from typing import Dict, Iterator, List, Union

from attrs import asdict
from more_executors import Executors
from pushsource import AmiPushItem, Source
from starmap_client.models import QueryResponse, Workflow

from ..push import MarketplacesVMPush
from ..push.items import MappedVMIPushItem, State

log = logging.getLogger("pubtools.marketplacesvm")


class CommunityVMPush(MarketplacesVMPush):
    """Upload an AMI to S3 and update RHSM."""

    _REQUEST_THREADS = int(os.environ.get("COMMUNITY_PUSH_REQUEST_THREADS", "5"))

    @property
    def raw_items(self) -> Iterator[AmiPushItem]:
        """
        Load all push items from the given source(s) and yield them.

        Yields:
            The AmiPushItems from the given sources.
        """
        for source_url in self.args.source:
            with Source.get(source_url) as source:
                log.info("Loading items from %s", source_url)
                for item in source:
                    if not isinstance(item, AmiPushItem):
                        log.warning(
                            "Push Item %s at %s is not an AmiPushItem, dropping it from the queue.",
                            item.name,
                            item.src,
                        )
                        continue
                    yield item

    @property
    def mapped_items(self) -> List[Dict[str, Union[MappedVMIPushItem, QueryResponse]]]:
        """
        Return the mapped push item with destinations and metadata from StArMap.

        Returns
            The wrapped push item with the additional information from StArMap.
        """
        mapped_items = []
        for item in self.raw_items:
            log.info(
                "Retrieving the mappings for %s from %s using the community workflow.",
                item.name,
                self.args.starmap_url,
            )
            binfo = item.build_info
            query = self.starmap.query_image_by_name(
                name=binfo.name,
                version=binfo.version,
                workflow=Workflow.community,
            )
            log.info(
                "starmap query returned for %s : %s ",
                item.name,
                json.dumps(
                    {"name": binfo.name, "version": binfo.version, "query_response": asdict(query)}
                ),
            )
            item = MappedVMIPushItem(item, query.clouds)
            # TODO: Check in the upcoming storage-mapping format an analogue way to do this
            # if not item.destinations:
            #    log.info("Filtering out archive with no destinations: %s", item.push_item.src)
            #    continue
            mapped_items.append({"item": item, "starmap_query": query})
        return mapped_items

    def _push_to_community(
        self, mapped_item: MappedVMIPushItem, starmap_query: QueryResponse
    ) -> None:
        """
        Perform the whole community workflow to upload the AMI and update RHSM.

        Args:
            mapped_item
                The item to process.
        Returns:
            Dictionary with the resulting operation for the Collector service.
        """
        # TODO: Implement the community workflow
        log.debug("StArMap: %s", starmap_query)
        log.debug("PushItem: %s", mapped_item)
        raise NotImplementedError("Not implemented yet")

    def run(self):
        """Execute the community_push command workflow."""
        mapped_items = self.mapped_items
        executor = Executors.thread_pool(
            name="pubtools-marketplacesvm-community-push",
            max_workers=min(max(len(mapped_items), 1), self._REQUEST_THREADS),
        )

        to_await = []
        result = []
        for item in mapped_items:
            to_await.append(
                executor.submit(self._push_to_community, item["item"], item["starmap_query"])
            )

        # waiting for results
        for f_out in to_await:
            result.extend(f_out.result())

        # process result for failures
        failed = False
        for r in result:
            if r.get("state", "") != State.PUSHED:
                failed = True

        # send to collector
        log.info("Collecting results")
        self.collect_push_result(result)

        if failed:
            log.error("Community VM push failed")
            sys.exit(30)

        # FIXME: Remove the coverage skip when the command gets properly implemented
        log.info("Community VM push completed")  # pragma: no cover
