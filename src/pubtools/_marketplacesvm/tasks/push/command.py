# SPDX-License-Identifier: GPL-3.0-or-later
import datetime
import json
import logging
import os
from typing import Any, Dict, Iterator, List, Optional, Tuple, TypedDict, Union, cast

from attrs import asdict, evolve
from more_executors import Executors
from pushsource import AmiPushItem, Source, VHDPushItem, VMIPushItem
from starmap_client.models import Destination, QueryResponseEntity, Workflow

from ...arguments import SplitAndExtend
from ...services import CloudService, CollectorService, StarmapService
from ...task import RUN_RESULT, MarketplacesVMTask
from ...utils import CLOUD_NAME_FOR_PI
from ..push.items import MappedVMIPushItemV2, State

log = logging.getLogger("pubtools.marketplacesvm")
UPLOAD_RESULT = Tuple[MappedVMIPushItemV2, QueryResponseEntity]


class PublishDict(TypedDict):
    """Data necessary for publish process."""

    mapped_item: MappedVMIPushItemV2
    marketplace: str
    destination: Destination
    starmap_query: QueryResponseEntity


class MarketplacesVMPush(MarketplacesVMTask, CloudService, CollectorService, StarmapService):
    """Push and publish content to various cloud marketplaces."""

    _REQUEST_THREADS = int(os.environ.get("MARKETPLACESVM_PUSH_REQUEST_THREADS", "5"))
    _PROCESS_THREADS = int(os.environ.get("MARKETPLACESVM_PUSH_PROCESS_THREADS", "10"))
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
                    self.builds_borg.received_builds.add(item.build_info.id)
                    yield item

    @property
    def mapped_items(self) -> List[Dict[str, Union[MappedVMIPushItemV2, QueryResponseEntity]]]:
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
            cloud = CLOUD_NAME_FOR_PI[type(item)]
            query = self.query_image_by_name(
                name=name,
                version=binfo.version,
            )
            query = self.filter_for(query, workflow=Workflow.stratosphere, cloud=cloud)
            if query:
                query_returned_from_starmap = query[0]
                log.info(
                    "starmap query returned for %s : %s",
                    item.name,
                    json.dumps(
                        {
                            "name": binfo.name,
                            "version": binfo.version,
                            "query_response": asdict(query_returned_from_starmap),
                        }
                    ),
                )
                item = MappedVMIPushItemV2(item, query_returned_from_starmap)
                if not item.destinations:
                    log.info("Filtering out archive with no destinations: %s", item.push_item.src)
                    continue
                mapped_items.append({"item": item, "starmap_query": query_returned_from_starmap})
            else:
                self._SKIPPED = True
                log.error(f"No marketplace mappings found for {binfo.name} on cloud {cloud}")
        return mapped_items

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
        self,
        marketplace: str,
        dest: Destination,
        push_item: VMIPushItem,
        pre_push: bool = True,
        modular_push: bool = False,
    ) -> VMIPushItem:
        """
        Publish the VM image to all required marketplace listings.

        Args:
            marketplace:
                The account name (alias) for the marketplace to publish.
            dest:
                The marketplace specific identifier of destination
            push_item
                The item to publish in a cloud marketplace listing.
            pre_push
                If True it will only associate the images without publishing, if possible.
                This defaults to True
            modular_push
                If True it will only perform a submission for a particular plan instead of for the
                whole offer (False).
                This defaults to False
        Returns:
            The push item after publishing.
        """
        try:
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
                check_base_sas_only=dest.vhd_check_base_sas_only,
                modular_push=modular_push,
            )

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

    def _push_upload(
        self, mapped_item: MappedVMIPushItemV2, starmap_query: QueryResponseEntity
    ) -> UPLOAD_RESULT:
        """Upload the mapped item to the storage accounts for all its marketplaces."""
        for marketplace in mapped_item.marketplaces:
            # Upload the VM image to the marketplace
            # In order to get the correct destinations we need to first pass the result of
            # get_push_item_from_marketplace.
            pi = mapped_item.get_push_item_for_marketplace(marketplace)
            # Since we will have a single upload for each marketplace and each PushItem may contain
            # multiple destinations within each marketplace, we may merge the StArMap "meta"
            # safely as the upload will just take advantage of their "sharing_accounts"
            # which es expected to be the same for all destinations within a same marketplace.
            meta = {}
            for d in pi.dest:
                meta.update(mapped_item.get_metadata_for_mapped_item(d) or {})
            pi = self._upload(
                marketplace,
                pi,
                custom_tags=mapped_item.get_tags_for_marketplace(marketplace),
                accounts=meta.get("sharing_accounts", []),
                ami_version_template=mapped_item.get_ami_version_template_for_mapped_item(
                    marketplace
                ),
            )
            mapped_item.update_push_item_for_marketplace(marketplace, pi)
        return mapped_item, starmap_query

    def _group_items(self, upload_result: List[UPLOAD_RESULT]) -> Dict[str, List[PublishDict]]:
        # Go through destinations and mappings to ensure that we are pushing
        # to only a single marketplace + dest at a time.
        publish_map: Dict[str, List[PublishDict]] = {}
        for mapped_item, starmap_query in upload_result:
            for marketplace in mapped_item.marketplaces:
                pi = mapped_item.get_push_item_for_marketplace(marketplace)
                for dest in pi.dest:
                    if not dest.architecture or dest.architecture == pi.release.arch:
                        destination = cast(Destination, dest)
                        if isinstance(pi, AmiPushItem):
                            # Product ID are unique enough in the AWS marketplace
                            group_name = f"aws-{destination.destination}"
                        elif isinstance(pi, VHDPushItem):
                            # Offer names can be the same among different accounts,
                            # but they do not conflict with each other
                            # PushItems to the same offer need to be released sequentially
                            offer_name = destination.destination.split("/")[0]
                            group_name = f"azure-{marketplace}-{offer_name}"

                        publish_dict: PublishDict = {
                            "mapped_item": mapped_item,
                            "marketplace": marketplace,
                            "destination": destination,
                            "starmap_query": starmap_query,
                        }
                        publish_map.setdefault(group_name, []).append(publish_dict)

        return publish_map

    def _push_pre_publish(self, upload_result: List[UPLOAD_RESULT]) -> Dict[str, List[PublishDict]]:
        """Perform the pre-publish routine call.

        Args:
            upload_result:
                The items to process.

        Returns:
            The processed items.
        """
        release_groups = self._group_items(upload_result)
        for release_group in release_groups.values():
            for release_data in release_group:
                mapped_item = release_data["mapped_item"]
                marketplace = release_data["marketplace"]
                destination = release_data["destination"]
                starmap_meta = destination.meta
                modular_push = bool(starmap_meta.get("modular_push", False))

                # Get the push item for the current marketplace
                pi = mapped_item.get_push_item_for_marketplace_and_destination(
                    marketplace, destination
                )

                # Associate image with Product/Offer/Plan and publish only if it's not a pre-push
                if pi.state != State.UPLOADFAILED and not self.args.pre_push:
                    log.info(
                        "Preparing to publish the item %s to %s on %s.",
                        pi.name,
                        destination.destination,
                        marketplace.upper(),
                    )
                    pi = evolve(pi, dest=[destination.destination])
                    pi, _ = self.cloud_instance(marketplace).pre_publish(
                        pi,
                        check_base_sas_only=destination.vhd_check_base_sas_only,
                        modular_push=modular_push,
                    )
                    log.info(
                        "Preparation complete for item %s to %s.",
                        pi.name,
                        marketplace.upper(),
                    )
                    mapped_item.update_push_item_for_marketplace(marketplace, pi)
        return release_groups

    def _push_publish(self, release_groups: Dict[str, List[PublishDict]]) -> List[Dict[str, Any]]:
        """
        Perform the publishing for the the VM images .

        Args:
            upload_result
                The items to process.
        Returns:
            Dictionary with the resulting operation for the Collector service.
        """

        def push_function(
            publish_group: List[PublishDict],
        ) -> List[Dict[str, Any]]:
            results = []
            for publish_data in publish_group:
                mapped_item = publish_data["mapped_item"]
                marketplace = publish_data["marketplace"]
                destination = publish_data["destination"]
                starmap_query = publish_data["starmap_query"]
                starmap_meta = destination.meta
                modular_push = starmap_meta.get("modular_push", False)

                # Get the push item for the current marketplace
                pi = mapped_item.get_push_item_for_marketplace_and_destination(
                    marketplace, destination
                )

                # Associate image with Product/Offer/Plan and publish only if it's not a pre-push
                if pi.state != State.UPLOADFAILED and not self.args.pre_push:
                    pi = self._publish(
                        marketplace,
                        destination,
                        pi,
                        pre_push=False,
                        modular_push=modular_push,
                    )
                elif pi.state != State.UPLOADFAILED and self.args.pre_push:
                    # Set the state as PUSHED when the operation is nochannel
                    pi = evolve(pi, state=State.PUSHED)

                # Update the destinations from List[Destination] to List[str] for collection
                dest_list_str = [destination.destination]
                push_item_for_collection = evolve(pi, dest=dest_list_str)
                mapped_item.update_push_item_for_marketplace(marketplace, pi)

                # Append the data for collection
                results.append(
                    {
                        "push_item": push_item_for_collection,
                        "state": pi.state,
                        "cloud_info": {
                            "account": marketplace,
                            "provider": mapped_item.starmap_query_entity.cloud,
                        },
                        "destinations": mapped_item.starmap_query_entity.mappings[
                            marketplace
                        ].destinations,
                        "starmap_query": starmap_query,
                    }
                )
            return results

        res_output = []
        to_await = []
        executor = Executors.thread_pool(
            name="pubtools-marketplacesvm-push-regions",
            max_workers=min(max(len(release_groups), 1), self._PROCESS_THREADS),
        )

        for release_group in release_groups.values():
            to_await.append(executor.submit(push_function, release_group))

        for f_out in to_await:
            res_output.extend(f_out.result())

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
            if result.get("cloud_info"):
                res_dict["cloud_info"] = result["cloud_info"]
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
        grouped_data = self._push_pre_publish(upload_result)

        # 4 - Publish the uploaded images letting the external function to control the threads
        result = self._push_publish(grouped_data)

        # process result for failures
        failed = False
        for r in result:
            if r.get("state", "") != State.PUSHED:
                failed = True
            else:
                # Store the successful build ID for future evaluation if needed
                build_id = r["push_item"].build_info.id
                self.builds_borg.processed_builds.add(build_id)

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
