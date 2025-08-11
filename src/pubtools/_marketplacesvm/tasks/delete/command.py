# SPDX-License-Identifier: GPL-3.0-or-later
import datetime
import json
import logging
import os
from typing import Any, Dict, Iterator, List, Optional, Tuple

from attrs import asdict, evolve
from pushsource import AmiPushItem, Source, VHDPushItem, VMIPushItem

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
                    self.builds_borg.received_builds.add(item.build_info.id)
                    yield item

    @property
    def deletion_items(self) -> List[VMIPushItem]:
        """Load and filter out all push items which are going to be deleted.

        Returns:
            List[VMIPushItem]: List with all push items to be deleted.
        """
        if not self.args.limit:
            return list(self.raw_items)

        filtered_push_items = []
        for item in self.raw_items:
            item_name = getattr(item, "image_id", None) or item.name
            if item_name in self.args.limit:
                filtered_push_items.append(item)
        return filtered_push_items

    def set_ami_invisible_rhsm(self, push_item: AmiPushItem, provider: str) -> None:
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
                product = self.get_rhsm_product(push_item.release.product, img_type, provider)
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

    def _get_provider_details(self, push_item: VMIPushItem) -> Tuple[str, List[str]]:
        if push_item.cloud_info:
            return push_item.cloud_info.provider, [push_item.cloud_info.account]
        provider = push_item.marketplace_entity_type
        account = self._convert_provider_name(provider)
        return provider, account

    def _set_ami_invisible(self, push_item: AmiPushItem, provider: Optional[str] = None) -> None:
        if not provider:
            return
        img_id = push_item.image_id
        log.debug("Marking AMI %s as invisible on RHSM for the provider %s.", img_id, provider)
        try:
            self.set_ami_invisible_rhsm(push_item, provider)
        except Exception as err:
            log.warning(
                "Failed to mark %s invisible on RHSM: %s",
                img_id,
                err,
                stack_info=True,
                exc_info=True,
            )

    def _delete_vmi(
        self,
        push_item: VMIPushItem,
        marketplaces: List[str],
        image_reference: str,
        provider: Optional[str] = None,
        **kwargs,
    ) -> VMIPushItem:
        pi = push_item
        if push_item.build in self.args.builds:
            if self.args.dry_run:
                self._set_ami_invisible(push_item, provider)
                log.info("Would have deleted: %s in build %s", image_reference, push_item.build)
                self._SKIPPED = True
                pi = evolve(push_item, state=State.SKIPPED)
                return pi
            for marketplace in marketplaces:
                self._set_ami_invisible(push_item, provider)
                log.info(
                    "Deleting %s in account %s",
                    image_reference,
                    marketplace,
                )
                pi, res = self.cloud_instance(marketplace).delete_push_images(
                    push_item, keep_snapshot=self.args.keep_snapshot, **kwargs
                )
                log.info(
                    "Delete finished for %s in account %s",
                    image_reference,
                    marketplace,
                )
                if res and isinstance(res, tuple) and res[0] is not None:
                    pi = evolve(pi, state=State.DELETED)
                    return pi
                else:
                    log.warning(
                        f"No deletion response for {pi.name} on {marketplace}, marking as MISSING."
                    )
                    pi = evolve(pi, state=State.MISSING)
        return pi

    def _delete(
        self,
        push_item: VMIPushItem,
        **kwargs,
    ) -> VMIPushItem:
        if isinstance(push_item, AmiPushItem):
            image_ref = push_item.image_id
            provider, marketplaces = self._get_provider_details(push_item)
        elif isinstance(push_item, VHDPushItem):
            image_ref = push_item.name
            provider = None
            if push_item.cloud_info:
                marketplaces = [push_item.cloud_info.account]
            else:
                # If we don't have cloud info we will need to try either
                marketplaces = ["azure-na", "azure-emea"]
        return self._delete_vmi(push_item, marketplaces, image_ref, provider, **kwargs)

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
            "--limit",
            help="Only remove the specified VMIs by their ID (AMI) or name (VHD)",
            action=SplitAndExtend,
            split_on=",",
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
        result = []
        for item in self.deletion_items:
            result.append(self._delete(item))

        # process result for failures
        failed = False
        if not result:
            failed = True
            log.error("No AmiPushItems to process")
        for r in result:
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
