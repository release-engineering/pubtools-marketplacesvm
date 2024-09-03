# SPDX-License-Identifier: GPL-3.0-or-later
import datetime
import json
import logging
import os
from typing import Any, Dict, Iterator, List

from attrs import asdict, evolve
from more_executors import Executors
from pushsource import AmiPushItem, Source, VMIPushItem

from ...arguments import SplitAndExtend
from ...services import CloudService, CollectorService
from ...services.rhsm import AwsRHSMClientService
from ...task import RUN_RESULT, MarketplacesVMTask
from ..push.items import State

log = logging.getLogger("pubtools.marketplacesvm")


class VMDelete(MarketplacesVMTask, CloudService, CollectorService, AwsRHSMClientService):
    """Delete an image from a cloud provider."""

    _REQUEST_THREADS = int(os.environ.get("DELETE_IMAGES_REQUEST_THREADS", "5"))
    _SKIPPED = False

    def __init__(self, *args, **kwargs):
        """Initialize the VMDelete instance."""
        super(VMDelete, self).__init__(*args, **kwargs)

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
                    self.builds_borg.received_builds.add(item.build_info.id)
                    yield item

    def update_rhsm_metadata(self, push_item: AmiPushItem) -> None:
        """
        Update image in RHSM to 'invisible'.

        Args:
            push_item (AmiPushItem)
                Push item to pull information from.
            provider (str)
                Provider that the image resides at.
        """
        if self.rhsm_image_ids and push_item.image_id not in self.rhsm_image_ids:
            log.warning("AMI image: %s not found, skipping update in rhsm.", push_item.image_id)
        else:
            try:
                img_type = push_item.type or ""
                product = self.get_rhsm_product(
                    push_item.release.product, img_type, push_item.marketplace_entity_type
                )
            except RuntimeError:
                log.info("%s not found in RHSM", push_item.release.product)
                return
            image_meta = {
                "image_id": push_item.image_id,
                "image_name": push_item.name,
                "arch": push_item.release.arch,
                "product_name": product["name"],
                "version": push_item.release.version or None,
                "variant": push_item.release.variant or None,
                "status": "invisible",
            }
            if self.args.dry_run:
                log.info("Would have updated image %s in rhsm", push_item.image_id)
                return

            log.info("Attempting to update the existing image %s in rhsm", push_item.image_id)
            out = self.rhsm_client.aws_update_image(**image_meta)
            resp = out.result()
            if not resp.ok:
                log.error("Failed updating image %s", push_item.image_id)
                resp.raise_for_status()

            log.info("Existing image %s succesfully updated in rhsm", push_item.image_id)

    def collect_push_result(self, results: List[AmiPushItem]) -> Dict[str, Any]:
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
            res_dict = asdict(result)
            # dict can't be modified during iteration.
            # so iterate over list of keys.
            for key in list(res_dict):
                if res_dict[key] is None:
                    del res_dict[key]
            mod_result.append(res_dict)
            push_items.append(result)

        metadata = json.dumps(mod_result, default=convert, indent=2, sort_keys=True)
        self.collector.update_push_items(push_items).result()
        return self.collector.attach_file("clouds.json", metadata).result()

    def _convert_provider_name(self, provider_name: str) -> List[str]:
        # Since we're only focused on AWS these are the accounts we're dealing with.
        # AmiProduct is a list as there's no way of telling which account the image
        # is on until we try to delete it.
        # Eventually we might want to add to pushsource a provider name field.
        accounts = {
            "AWS": ["aws-us-storage"],
            "AGOV": ["aws-us-gov-storage"],
            "ACN": ["aws-china-storage"],
            "AmiProduct": ["aws-na", "aws-emea"],
        }
        return accounts[provider_name]

    def _delete(
        self,
        push_item: VMIPushItem,
        **kwargs,
    ) -> VMIPushItem:
        marketplaces = self._convert_provider_name(push_item.marketplace_entity_type)
        if push_item.build in self.args.builds:
            if self.args.dry_run:
                log.info("Would have deleted: %s in build %s", push_item.image_id, push_item.build)
                self._SKIPPED = True
                pi = evolve(push_item, state=State.SKIPPED)
                self.update_rhsm_metadata(push_item)
                return pi
            # Cycle through potential marketplaces, this only matters in AmiProducts
            # as the build could exist in either aws-na or aws-emea.
            failed_marketplace = []
            for marketplace in marketplaces:
                try:
                    log.info(
                        "Deleting %s in account %s",
                        push_item.image_id,
                        marketplace,
                    )
                    pi = self.cloud_instance(marketplace).delete_push_images(
                        push_item, keep_snapshot=self.args.keep_snapshot, **kwargs
                    )
                    log.info(
                        "Delete finished for %s in account %s",
                        push_item.image_id,
                        marketplace,
                    )
                    pi = evolve(pi, state=State.DELETED)
                    self.update_rhsm_metadata(push_item)
                    return pi
                except Exception as exc:
                    # If we failed the image might not exist, not necessarily an error
                    delete_error = exc
                    failed_marketplace.append(marketplace)
            if len(failed_marketplace) == len(marketplaces):
                log.info(
                    "Failed to delete %s in %s:%s",
                    push_item.image_id,
                    ",".join(failed_marketplace),
                    delete_error,
                    stack_info=True,
                )
                self._SKIPPED = True
                pi = evolve(push_item, state=State.UPLOADFAILED)
                return pi
        log.info("Skipped: %s in build %s", push_item.image_id, push_item.build)
        self._SKIPPED = True
        pi = evolve(push_item, state=State.SKIPPED)
        return pi

    def add_args(self):
        """Include the required CLI arguments for VMDelete."""
        super(VMDelete, self).add_args()

        self.parser.add_argument(
            "--builds",
            help="The builds to delete images from",
            type=str,
            action=SplitAndExtend,
            split_on=",",
        )

        self.parser.add_argument(
            "--dry-run",
            help="Skip destructive actions on rhsm or AWS",
            action="store_true",
        )

        self.parser.add_argument(
            "--keep-snapshot",
            help="Do not delete snapshot from AWS",
            action="store_true",
        )

        self.parser.add_argument(
            "source",
            nargs="+",
            help="Source(s) of content to be pushed",
            action=SplitAndExtend,
            split_on=",",
        )

    def run(self, collect_results: bool = True, allow_empty_targets: bool = False) -> RUN_RESULT:
        """Execute the delete command workflow."""
        mapped_items = [x for x in self.raw_items]
        executor = Executors.thread_pool(
            name="pubtools-marketplacesvm-delete",
            max_workers=min(max(len(mapped_items), 1), self._REQUEST_THREADS),
        )

        to_await = []
        result = []
        if len(mapped_items) == 0:
            log.error("No AmiPushItems to process")
            return RUN_RESULT(False, self._SKIPPED, [])
        for mapped_item in mapped_items:
            to_await.append(executor.submit(self._delete, mapped_item))

        # waiting for results
        for f_out in to_await:
            result.append(f_out.result())
        # process result for failures
        failed = False
        for r in result:
            if r.state == State.UPLOADFAILED:
                failed = True
            # Store the successful build ID for future evaluation if needed
            build_id = r.build_info.id
            self.builds_borg.processed_builds.add(build_id)

        # send to collector
        if collect_results:
            log.info("Collecting results")
            self.collect_push_result(result)

        if failed:
            log.error("Delete failed")
        else:
            log.info("Delete completed")
        return RUN_RESULT(not failed, self._SKIPPED, result)
