# SPDX-License-Identifier: GPL-3.0-or-later
import datetime
import json
import logging
import os
from copy import copy
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

from attrs import asdict, evolve
from more_executors import Executors
from pushsource import Source, VMIPushItem
from starmap_client.models import Destination, QueryResponse

from ...arguments import SplitAndExtend
from ...services import CloudService, CollectorService, StarmapService
from ...task import RUN_RESULT, MarketplacesVMTask
from ..push.items import MappedVMIPushItem, State

log = logging.getLogger("pubtools.marketplacesvm")
UPLOAD_RESULT = Tuple[MappedVMIPushItem, QueryResponse]


class MarketplacesVMPush(MarketplacesVMTask, CloudService, CollectorService, StarmapService):
    """Push and publish content to various cloud marketplaces."""

    _REQUEST_THREADS = int(os.environ.get("MARKETPLACESVM_PUSH_REQUEST_THREADS", "5"))
    _PROCESS_THREADS = int(os.environ.get("MARKETPLACESVM_PUSH_PROCESS_THREADS", "2"))
    _SKIPPED = False

    @property
    def raw_items(self) -> Iterator[VMIPushItem]:
        """
        Load all push items from the given source(s) and yield them.

        Yields:
            The VMIPushItems from the given sources.
        """
        for source_url in self.args.source:
            with Source.get(source_url) as source:
                log.info("Loading items from %s", source_url)
                for item in source:
                    if not isinstance(item, VMIPushItem):
                        log.warning(
                            "Push Item %s at %s is not a VMIPushItem, dropping it from the queue.",
                            item.name,
                            item.src,
                        )
                        continue
                    # filter out CoreOS Assembler PushItems for government regions
                    elif (item.src and item.src.startswith("ami")) and (
                        item.region and "-gov-" in item.region
                    ):
                        log.info("Skipping PushItem %s for region %s", item.name, item.region)
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
            log.info("Retrieving the mappings for %s from %s", item.name, self.args.starmap_url)
            binfo = item.build_info
            if item.marketplace_name:
                name = binfo.name + "-" + item.marketplace_name
            else:
                name = binfo.name
            query = self.starmap.query_image_by_name(
                name=name,
                version=binfo.version,
            )
            if query:
                query_returned_from_starmap = query
                log.info(
                    "starmap query returned for %s : %s ",
                    item.name,
                    json.dumps(
                        {
                            "name": binfo.name,
                            "version": binfo.version,
                            "query_response": asdict(query),
                        }
                    ),
                )
                query = self._apply_starmap_overrides(query)
                item = MappedVMIPushItem(item, query.clouds)
                if not item.destinations:
                    log.info("Filtering out archive with no destinations: %s", item.push_item.src)
                    continue
                mapped_items.append({"item": item, "starmap_query": query_returned_from_starmap})
            else:
                self._SKIPPED = True
                log.error(f"No mappings found for {binfo.name}")
        return mapped_items

    def _apply_starmap_overrides(self, query: QueryResponse) -> QueryResponse:
        """
        Override the StArMap destinations when they're given by command line args.

        Args:
            query
                The original StArMap response

        Returns:
            The original response if no destinations are provided by command line or
            a new response with the changed destinations.
        """
        if not self.args.repo:  # No destinations given by command line args
            return query

        # Helper function to deserialize the JSON destinations
        def make_destination(json: Dict[str, Any]) -> Destination:
            data = copy(json)  # to prevent messing with the original dict
            data.setdefault("overwrite", False)
            data.setdefault("architecture", "x86_64")
            return Destination.from_json(data)

        # For each cloud convert the destinations into Destination object
        mapping = self.args.repo
        for cloud_name in mapping:
            if isinstance(mapping[cloud_name], list):  # List of destinations
                destinations = mapping[cloud_name]
            else:  # Single destination
                destinations = [mapping[cloud_name]]

            # NOTE: dictionary is mutable thus we can do this even though QueryResponse is frozen.
            query.clouds[cloud_name] = [make_destination(d) for d in destinations]
        return query

    def _upload(
        self,
        marketplace: str,
        push_item: VMIPushItem,
        custom_tags: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> VMIPushItem:
        """
        Upload a single push item to the cloud marketplace and update the status.

        Args:
            marketplace:
                The account name (alias) for the marketplace to upload.
            push_item
                The item to upload
            custom_tags:
                Optional tags to be applied alongside the default ones from upload.
            kwargs:
                Additional arguments for CloudProviders
        Returns:
            The push item after the upload.
        """
        try:
            log.info("Uploading the item %s to %s.", push_item.name, marketplace.upper())
            pi, _ = self.cloud_instance(marketplace).upload(
                push_item, custom_tags=custom_tags, **kwargs
            )
            log.info("Upload finished for %s on %s", push_item.name, marketplace.upper())
            pi = evolve(pi, state=State.NOTPUSHED)
        except Exception as exc:
            log.exception("Failed to upload %s: %s", push_item.name, str(exc), stack_info=True)
            pi = evolve(push_item, state=State.UPLOADFAILED)
        return pi

    def _publish(
        self, marketplace: str, push_item: VMIPushItem, pre_push: bool = True
    ) -> VMIPushItem:
        """
        Publish the VM image to all required marketplace listings.

        Args:
            marketplace:
                The account name (alias) for the marketplace to publish.
            push_item
                The item to publish in a cloud marketplace listing.
            pre_push
                If True it will only associate the images without publishing, if possible.
                This defaults to True
        Returns:
            The push item after publishing.
        """
        try:
            last_destination = ""
            for dest in push_item.dest:
                # We don't want to publish again the same offer when pre-push == False (go live)
                curr_dest = dest.destination.split("/")[0]  # get just the offer name, if applicable
                if not pre_push and curr_dest == last_destination:
                    log.info(
                        "Push already done for offer %s on %s.", curr_dest, marketplace.upper()
                    )
                    continue

                log.info(
                    "Pushing \"%s\" (pre-push=%s) to %s on %s.",
                    push_item.name,
                    pre_push,
                    dest.destination,
                    marketplace.upper(),
                )
                single_dest_item = evolve(push_item, dest=[dest.destination])

                pi, _ = self.cloud_instance(marketplace).publish(
                    single_dest_item,
                    nochannel=pre_push,
                    overwrite=dest.overwrite,
                    restrict_version=dest.restrict_version,
                    restrict_major=dest.restrict_major,
                    restrict_minor=dest.restrict_minor,
                )

                last_destination = curr_dest
            # Once we process all destinations we set back the list of destinations
            pi = evolve(pi, dest=push_item.dest, state=State.PUSHED)
        except Exception as exc:
            log.exception(
                "Failed to publish %s on %s: %s",
                push_item.name,
                marketplace.upper(),
                str(exc),
                stack_info=True,
            )
            pi = evolve(push_item, state=State.NOTPUSHED)
        return pi

    def _allowed_to_publish(self, mapped_item: MappedVMIPushItem) -> bool:
        """
        Return True whenever the Marketplace publish is allowed, False otherwise.

        It uses the combination of `--pre-push` and StArMap's `stage-preview` to determine
        whether it's safe to proceed to publish or not.
        """
        # The pre_push should only allow publishing when it's not a pre_push
        if not self.args.pre_push:
            return True
        # For other cases we must not publish
        return False

    def _push_upload(
        self, mapped_item: MappedVMIPushItem, starmap_query: QueryResponse
    ) -> UPLOAD_RESULT:
        """Upload the mapped item to the storage accounts for all its marketplaces."""
        for marketplace in mapped_item.marketplaces:
            # Upload the VM image to the marketplace
            # In order to get the correct destinations we need to first pass the result of
            # get_push_item_from_marketplace.

            pi = self._upload(
                marketplace,
                mapped_item.get_push_item_for_marketplace(marketplace),
                custom_tags=mapped_item.get_tags_for_marketplace(marketplace),
                accounts=mapped_item.meta.get("sharing_accounts", []),
            )
            mapped_item.update_push_item_for_marketplace(marketplace, pi)
        return mapped_item, starmap_query

    def _push_pre_publish(self, upload_result: List[UPLOAD_RESULT]) -> List[UPLOAD_RESULT]:
        """Perform the pre-publish routine call.

        Args:
            upload_result:
                The items to process.

        Returns:
            The processed items.
        """
        res = []
        for mapped_item, starmap_query in upload_result:
            for marketplace in mapped_item.marketplaces:
                pi = mapped_item.get_push_item_for_marketplace(marketplace)
                if pi.state != State.UPLOADFAILED and self._allowed_to_publish(mapped_item):
                    destination_list = pi.dest
                    for dest in pi.dest:
                        log.info(
                            "Preparing to publish the item %s to %s on %s.",
                            pi.name,
                            dest.destination,
                            marketplace.upper(),
                        )
                        pi = evolve(pi, dest=[dest.destination])
                        pi, _ = self.cloud_instance(marketplace).pre_publish(pi)
                        log.info(
                            "Preparation complete for item %s to %s.",
                            pi.name,
                            marketplace.upper(),
                        )
                    # Set back the original destinations after processing
                    pi = evolve(pi, dest=destination_list)
                    mapped_item.update_push_item_for_marketplace(marketplace, pi)
            res.append((mapped_item, starmap_query))
        return res

    def _push_publish(self, upload_result: List[UPLOAD_RESULT]) -> List[Dict[str, Any]]:
        """
        Perform the publishing for the the VM images.

        Args:
            upload_result
                The items to process.
        Returns:
            Dictionary with the resulting operation for the Collector service.
        """

        def push_function(mapped_item, marketplace, starmap_query) -> Dict[str, Any]:
            # Get the push item for the current marketplace
            pi = mapped_item.get_push_item_for_marketplace(marketplace)

            # Associate image with Product/Offer/Plan and publish only if it's not a pre-push
            if pi.state != State.UPLOADFAILED and self._allowed_to_publish(mapped_item):
                # The first publish should always be with `pre_push` set True because it might
                # happen that one offer with multiple plans would receive the same image and
                # we can't `publish` the offer with just the first plan changed and try to change
                # the others (every plan should be changed while the offer is still on draft).
                #
                # Then this first `_publish` call is intended to only associate the image with
                # all the offers/plans but not change it to live, when this is applicable.
                pi = self._publish(marketplace, pi)

                # Once we associated all the images with their offer/plans it's now safe to call
                # again the publish if and only if `pre_push == False`.
                # The indepondent operation will guarantee that the images are already associated
                # with the Product/Offer/Plan and just the go-live part is called.
                pi = self._publish(
                    marketplace,
                    pi,
                    pre_push=False,
                )
            elif pi.state != State.UPLOADFAILED and not self._allowed_to_publish(mapped_item):
                # Set the state as PUSHED when the operation is nochannel
                pi = evolve(pi, state=State.PUSHED)

            # Update the destinations from List[Destination] to List[str] for collection
            dest_list_str = [d.destination for d in pi.dest]
            push_item_for_collection = evolve(pi, dest=dest_list_str)
            mapped_item.update_push_item_for_marketplace(marketplace, pi)

            # Append the data for collection
            return {
                "push_item": push_item_for_collection,
                "state": pi.state,
                "marketplace": marketplace,
                "destinations": mapped_item.clouds[marketplace],
                "starmap_query": starmap_query,
            }

        res_output = []

        # Sequentially publish the uploaded items for each marketplace.
        # It's recommended to do this operation sequentially since parallel publishing in the
        # same marketplace may cause errors due to the change set already being applied.
        for mapped_item, starmap_query in upload_result:
            to_await = []
            executor = Executors.thread_pool(
                name="pubtools-marketplacesvm-push-regions",
                max_workers=min(max(len(mapped_item.marketplaces), 1), self._PROCESS_THREADS),
            )

            for marketplace in mapped_item.marketplaces:
                to_await.append(
                    executor.submit(push_function, mapped_item, marketplace, starmap_query)
                )

            for f_out in to_await:
                res_output.append(f_out.result())

        return res_output

    def collect_push_result(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Collect the push results and sends its json to the collector.

        Args:
            results
                The list of dictionaries containing the result data for the push collector.

        Returns:
            The result of push collector `attach_file` call.
        """

        def convert(obj):
            if isinstance(obj, (datetime.datetime, datetime.date)):
                return obj.strftime("%Y%m%d")

        push_items = []
        mod_result = []
        for result in results:
            res_dict = asdict(result["push_item"])
            if result.get("starmap_query"):
                res_dict["starmap_query"] = asdict(result["starmap_query"])
            # dict can't be modified during iteration.
            # so iterate over list of keys.
            for key in list(res_dict):
                if res_dict[key] is None:
                    del res_dict[key]
            mod_result.append(res_dict)
            push_items.append(result["push_item"])

        metadata = json.dumps(mod_result, default=convert, indent=2, sort_keys=True)
        self.collector.update_push_items(push_items).result()
        return self.collector.attach_file("clouds.json", metadata).result()

    def add_args(self):
        """Include the required CLI arguments for MarketplacesVMPush."""
        super(MarketplacesVMPush, self).add_args()

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
            action="store_true",
            help=(
                "Pre-push mode: do as much as possible without making content "
                "available to end-users, then stop. May be used to improve the "
                "performance of a subsequent full push."
            ),
        )

        self.parser.add_argument(
            "--repo",
            help="Override the destinations of a cloud marketplace account for all push items. "
            "e.g: {'aws-na': [{'destination': 'c39fd...', overwrite: true}, ...]}",
            type=json.loads,
            default={},
        )

        self.parser.add_argument(
            "source",
            nargs="+",
            help="Source(s) of content to be pushed",
            action=SplitAndExtend,
            split_on=",",
        )

    def run(self, collect_results: bool = True, allow_empty_targets: bool = False) -> RUN_RESULT:
        """Execute the push command workflow."""
        # 1 - Map items
        mapped_items = self.mapped_items

        # 2 - Upload VM images to the marketplaces in parallel
        executor = Executors.thread_pool(
            name="pubtools-marketplacesvm-push-upload",
            max_workers=min(max(len(mapped_items), 1), self._REQUEST_THREADS),
        )

        to_upload = []
        upload_result = []
        for item in mapped_items:
            to_upload.append(
                executor.submit(self._push_upload, item["item"], item["starmap_query"])
            )

        # waiting for upload results
        for f_out in to_upload:
            upload_result.append(f_out.result())

        # 3 - Execute any pre-publishing routine
        upload_result = self._push_pre_publish(upload_result)

        # 4 - Publish the uploaded images letting the external function to control the threads
        result = self._push_publish(upload_result)

        # process result for failures
        failed = False
        for r in result:
            if r.get("state", "") != State.PUSHED:
                failed = True

        if not allow_empty_targets and not result:
            failed = True

        # 4 - Send resulting data to collector
        if collect_results:
            log.info("Collecting results")
            self.collect_push_result(result)

        if failed:
            log.error("Marketplace VM push failed")
        else:
            log.info("Marketplace VM push completed")
        if not self._SKIPPED and (allow_empty_targets and not result):
            self._SKIPPED = True
        return RUN_RESULT(not failed, self._SKIPPED, result)
