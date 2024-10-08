# SPDX-License-Identifier: GPL-3.0-or-later
import json
import logging
import os
from collections import namedtuple
from typing import Any, Dict, Iterator, List, Optional, TypedDict, cast

from attrs import asdict, evolve
from more_executors import Executors
from pushsource import AmiPushItem, Source, VMIPushItem
from requests import HTTPError, Response
from starmap_client.models import Destination, Workflow
from typing_extensions import NotRequired

from pubtools._marketplacesvm.tasks.community_push.items import ReleaseType, enrich_push_item

from ...cloud_providers.aws import name_from_push_item
from ...services.rhsm import AwsRHSMClientService
from ...task import RUN_RESULT
from ...utils import CLOUD_NAME_FOR_PI
from ..push import MarketplacesVMPush
from ..push.items import MappedVMIPushItemV2, State

log = logging.getLogger("pubtools.marketplacesvm")

SharingAccounts = Dict[str, List[str]]
PushItemAndSA = namedtuple("PushItemAndSA", ["push_item", "sharing_accounts"])
EnrichedPushItem = Dict[str, List[PushItemAndSA]]


class UploadParams(TypedDict):
    """Represent the parameters to start the community VM upload operation."""

    marketplace: str
    push_item: AmiPushItem
    accounts: NotRequired[List[str]]
    sharing_accounts: NotRequired[List[str]]
    snapshot_accounts: NotRequired[List[str]]


class CommunityVMPush(MarketplacesVMPush, AwsRHSMClientService):
    """Upload an AMI to S3 and update RHSM."""

    _PROCESS_THREADS = int(os.environ.get("COMMUNITY_PUSH_PROCESS_THREADS", "10"))
    _REQUIRE_BC = bool(
        os.environ.get("COMMUNITY_PUSH_REQUIRE_BILLING_CODES", "true").lower() == "true"
    )
    _SKIPPED = False

    def __init__(self, *args, **kwargs):
        """Initialize the CommunityVMPush instance."""
        self._rhsm_products: Optional[List[Dict[str, Any]]] = None
        super(CommunityVMPush, self).__init__(*args, **kwargs)

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

    @property
    def mapped_items(self) -> List[MappedVMIPushItemV2]:  # type: ignore [override]
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
            cloud = CLOUD_NAME_FOR_PI[type(item)]
            query = self.query_image_by_name(
                name=binfo.name,
                version=binfo.version,
            )
            query = self.filter_for(query, workflow=Workflow.community, cloud=cloud)
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
                        },
                        default=str,
                    ),
                )
                item = MappedVMIPushItemV2(item, query_returned_from_starmap)
                mapped_items.append(item)
            else:
                self._SKIPPED = True
                log.error(f"No community mappings found for {binfo.name} on cloud {cloud}")
        return mapped_items

    def in_rhsm(self, product: str, image_type: str, aws_provider_name: str) -> bool:
        """Check whether the product is present in rhsm for the provider.

        Args:
            product (str): The product name
            image_type (str): The image type (hourly or access)
            aws_provider_name (str): The AWS provider name

        Returns:
            True if the product is found in rhsm_products else False.
        """
        try:
            self.get_rhsm_product(product, image_type, aws_provider_name)
        except (RuntimeError, HTTPError) as er:
            log.error(er)
            return False
        return True

    def items_in_metadata_service(self, push_items: List[AmiPushItem]):
        """Check for all the push_items whether they are in rhsm or not.

        Args:
            push_items:
                List of enriched AmiPushItem to check on RHSM.

        Returns:
            False if any of item is missing in RHSM else True.
        """
        verified = True
        for pi in push_items:
            # Since the StArMap "meta" should be the same for all destinations
            # we can retrieve a push item from any marketplace at this moment
            # just to have all properties loaded before checking on RHSM
            if not self.in_rhsm(pi.release.product, pi.type, pi.marketplace_entity_type):
                log.error(
                    "Pre-push check in metadata service failed for %s at %s",
                    pi.name,
                    pi.src,
                )
                pi = evolve(pi, state="INVALIDFILE")
                verified = False
        return verified

    def update_rhsm_metadata(self, image: Any, push_item: AmiPushItem) -> None:
        """Update RHSM with the uploaded image info.

        First it creates the region of the image assuming it returns OK if the region
        is present. Then tries to update the existing image info.

        If the image info is not preset, it creates one.

        Args:
            image: The return result from ``AWSUploadService.publish``.
            push_item: The resulting push_item after uploading.
        """
        provider = push_item.marketplace_entity_type
        log.info("Creating region %s [%s]", push_item.region, provider)
        out = self.rhsm_client.aws_create_region(push_item.region, provider)

        response: Response = out.result()
        if not response.ok:
            log.error(
                "Failed creating region %s for image %s: %s",
                push_item.region,
                image.id,
                response.text,
            )
            response.raise_for_status()

        log.info("Registering image %s with RHSM", image.id)
        image_meta = {
            "image_id": image.id,
            "image_name": image.name,
            "arch": push_item.release.arch,
            "product_name": self.get_rhsm_product(
                push_item.release.product, push_item.type, provider
            )["name"],
            "version": push_item.release.version or None,
            "variant": push_item.release.variant or None,
        }
        log.info("Attempting to update the existing image %s in RHSM", image.id)
        log.debug("%s", image_meta)
        out = self.rhsm_client.aws_update_image(**image_meta)
        response = out.result()
        if not response.ok:
            log.warning(
                "Update to RHSM failed for %s with error code %s. "
                "Image might not be present on RHSM for update.\n%s",
                image.id,
                response.status_code,
                response.text,
            )

            log.info("Attempting to create new image %s in RHSM", image.id)
            image_meta.update({"region": push_item.region})
            log.debug("%s", image_meta)
            out = self.rhsm_client.aws_create_image(**image_meta)
            response = out.result()
            if not response.ok:
                log.error(
                    "Failed to create image %s in RHSM with error code %s\n%s",
                    image.id,
                    response.status_code,
                    response.text,
                )
                response.raise_for_status()
        log.info("Successfully registered image %s with RHSM", image.id)

    def _get_sharing_accounts(self, destination: Destination) -> SharingAccounts:
        """Return the sharing accounts configuration when provided by StArMap.

        Args:
            destination: The destination of a given push item to retrieve the sharing accounts.
        Returns:
            SharingAccounts: The dictionary containing the respective sharing accounts.
        """  # noqa: D202

        # Marketplace workflow has the accounts in the following format:
        #
        # # ...
        # # meta:
        # #   sharing_accounts:
        # #      - ACCOUNT_STR
        #
        # However this workflow has been originally implemented similarly to pubtools-ami
        # with the following_format:
        #
        # # meta:
        # #   accounts:
        # #     default|REGION_NAME:
        # #       - ACCONT_STR
        #
        # To support a common format for sharing accounts this method was updated to support
        # both ways:
        # The `sharing_accounts` in a similar way of the marketplace workflow, while maintaining the
        # previous `accounts` format for retrocompatibility.
        def set_accounts(acct_name: str, acct_dict: Dict[str, List[str]]) -> None:
            accts = destination.meta.get(acct_name)
            if not accts:
                log.warning(
                    "No %s definition in StArMap, leaving the defaults from credentials.", acct_name
                )
                return

            log.info("Loading %s from StArMap: %s", acct_name, accts)
            if isinstance(accts, dict):
                combined_accts = []
                for _, account in accts.items():  # expected format: Dict[str, str]]
                    if not isinstance(account, str):
                        w = f"Ignoring unsupported format for {acct_name} {type(account)}: {account}"  # noqa: E501
                        log.warning(w)
                        continue
                    combined_accts.append(account)
                log.debug("Loaded \"%s\": \"%s\" from StArMap.", acct_name, combined_accts)
                acct_dict.setdefault(acct_name, combined_accts)
            elif isinstance(accts, list):  # expected format: List[str]
                log.debug("Loaded the following accounts as \"%s\": %s", acct_name, accts)
                acct_dict.setdefault(acct_name, accts)

        result: SharingAccounts = {}
        set_accounts("accounts", result)
        set_accounts("sharing_accounts", result)
        set_accounts("snapshot_accounts", result)
        return result

    def enrich_mapped_items(
        self, mapped_items: List[MappedVMIPushItemV2]
    ) -> List[EnrichedPushItem]:
        """Load all missing information for each mapped item.

        It returns a list of dictionaries which contains the storage account and
        the push items for each account.

        Args:
            mapped_items (List[MappedVMIPushItemV2]): The list of mapped items.

        Returns:
            List[EnrichedPushItem]: List of resulting enriched push items.
        """
        result: List[EnrichedPushItem] = []
        for mapped_item in mapped_items:
            account_dict: EnrichedPushItem = {}
            for storage_account, mrobj in mapped_item.starmap_query_entity.mappings.items():
                log.info("Processing the storage account %s", storage_account)
                pi_and_sa_list: List[PushItemAndSA] = []
                for dest in mrobj.destinations:
                    pi = mapped_item.get_push_item_for_destination(dest)
                    log.debug("Mapped push item for %s: %s", storage_account, pi)
                    r = dest.meta.get("release") or {}
                    r_type_str = str(r.get("type", "")).lower()
                    r_type_str = "beta" if self.args.beta else r_type_str
                    if r_type_str:
                        release_type = ReleaseType(r_type_str)
                    else:
                        release_type = None
                    epi = enrich_push_item(
                        pi,
                        dest,
                        release_type=release_type,
                        require_bc=self._REQUIRE_BC,
                        billing_config=mapped_item.starmap_query_entity.billing_code_config,
                    )
                    log.debug("Enriched push item for %s: %s", storage_account, epi)

                    # SAP and RHEL-HA images are expected to be
                    # shipped only to hourly destinations
                    # See: https://gitlab.cee.redhat.com/exd-guild-distribution/cloud-image-tools/-/blob/master/cloudimgtools/create_staged_pushes.py#L330-348  # noqa: E501
                    if epi.type != "hourly" and epi.release.product in ("RHEL_HA", "SAP"):
                        log.warning(
                            "Skipping upload of '%s' for '%s' as the image is expected to be pushed"
                            " only to hourly destinations",
                            epi.src,
                            dest.destination,
                        )
                        continue

                    log.info(
                        "Adding push item \"%s\" with destination \"%s\" and type \"%s\" to the queue.",  # noqa: E501
                        epi.name,
                        epi.dest[0],
                        epi.type,
                    )
                    pi_and_sa = PushItemAndSA(epi, self._get_sharing_accounts(dest))
                    pi_and_sa_list.append(pi_and_sa)
                account_dict[storage_account] = pi_and_sa_list
            result.append(account_dict)
        return result

    def _upload(
        self,
        marketplace: str,
        push_item: VMIPushItem,
        custom_tags: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> VMIPushItem:
        # First we do the AMI upload in a similar way of the base class
        ship = not self.args.pre_push
        container = "%s-%s" % (self.args.container_prefix, push_item.region)
        try:
            accounts = kwargs.get("accounts") or kwargs.get("sharing_accounts")
            snapshot_accounts = kwargs.get("snapshot_accounts")
            log.info(
                "Uploading %s to region %s (type: %s, ship: %s, account: %s) with sharing accounts: %s and snapshot accounts: %s",  # noqa: E501
                push_item.src,
                push_item.region,
                push_item.type,
                ship,
                marketplace,
                accounts,
                snapshot_accounts,
            )
            pi, image = self.cloud_instance(marketplace).upload(
                push_item,
                custom_tags=custom_tags,
                container=container,
                accounts=accounts,
                snapshot_accounts=snapshot_accounts,
            )
            log.info("Upload finished for %s on %s", push_item.name, push_item.region)
        except Exception as exc:
            log.exception(
                "Failed to upload %s to %s-%s: %s",
                push_item.name,
                push_item.region,
                push_item.type,
                str(exc),
                stack_info=True,
            )
            pi = evolve(push_item, state=State.UPLOADFAILED)
            return pi

        # Then, if we're shipping the community image, we should update the RHSM
        # and change the the AWS group to "all" for the uploaded image
        if ship:
            try:
                self.update_rhsm_metadata(image, push_item)
                if push_item.public_image:
                    log.info("Releasing image %s publicly", image.id)
                    groups = ["all"]
                    # A repeat call to upload will only update the groups
                    pi, _ = self.cloud_instance(marketplace).upload(
                        push_item,
                        custom_tags=custom_tags,
                        container=container,
                        accounts=accounts,
                        snapshot_accounts=snapshot_accounts,
                        groups=groups,
                    )
            except Exception as exc:
                log.exception("Failed to publish %s: %s", push_item.name, str(exc), stack_info=True)
                pi = evolve(push_item, state=State.NOTPUSHED)
                return pi

        # Finally, if everything went well we return the updated push item
        log.info("Successfully uploaded %s [%s] [%s]", pi.name, pi.region, image.id)
        pi = evolve(pi, state=State.PUSHED)
        return pi

    def _check_product_in_rhsm(self, enriched_push_items: List[EnrichedPushItem]) -> bool:
        for enriched_item in enriched_push_items:
            for _, pi_and_sa_list in enriched_item.items():
                push_items = [x.push_item for x in pi_and_sa_list]
                if not self.items_in_metadata_service(push_items):
                    log.error("Pre-push verification of push items in metadata service failed")
                    return False
        return True

    def _push_to_community(self, push_queue: Iterator[UploadParams]) -> List[Dict[str, Any]]:
        """
        Consume the queue to perform the whole community workflow to upload the AMI and update RHSM.

        Args:
            push_queue
                Iterator with the required data to upload.
        Returns:
            Dictionary with the resulting operation for the Collector service.
        """
        to_await = []
        upload_result = []
        executor = Executors.thread_pool(
            name="pubtools-marketplacesvm-community-push",
            max_workers=self._PROCESS_THREADS,
        )

        # consume the queue
        for data in push_queue:
            to_await.append(executor.submit(self._upload, **data))

        # wait for results
        for f_out in to_await:
            upload_result.append(f_out.result())

        # Return the data for collection
        return [
            {
                "push_item": pi,
                "state": pi.state,
                "image_id": pi.image_id,
                "image_name": name_from_push_item(pi),
            }
            for pi in upload_result
        ]

    def _data_to_upload(
        self, enriched_push_items: List[EnrichedPushItem]
    ) -> Iterator[UploadParams]:
        """
        Generate the required data to perform the AMI upload and update RHSM.

        Args:
            enriched_push_items
                List of dictionaries and storage accounts with the region name and the push items.
        """
        for enriched_push_item in enriched_push_items:
            for storage_account, push_items_and_sa in enriched_push_item.items():
                for pi_and_sa in push_items_and_sa:
                    pi, sharing_accts = pi_and_sa

                    # Prepare the sharing accounts
                    additional_args = {}
                    extra_args = ["accounts", "sharing_accounts", "snapshot_accounts"]
                    for arg in extra_args:
                        content = sharing_accts.get(arg)
                        if content:
                            additional_args[arg] = content

                    # Generate the push items to upload
                    params = {"marketplace": storage_account, "push_item": pi, **additional_args}
                    yield cast(UploadParams, params)

    def add_args(self):
        """Include the required CLI arguments for CommunityVMPush."""
        super(CommunityVMPush, self).add_args()

        self.parser.add_argument(
            "--beta",
            help="Ship beta images instead of GA",
            action="store_true",
        )

        self.parser.add_argument(
            "--container-prefix",
            help="prefix to storage container for upload",
            default="redhat-cloudimg",
        )

    def run(self, collect_results: bool = True, allow_empty_targets: bool = False) -> RUN_RESULT:
        """Execute the community_push command workflow."""
        enriched_push_items = self.enrich_mapped_items(self.mapped_items)
        if not self._check_product_in_rhsm(enriched_push_items):
            return RUN_RESULT(False, False, {})  # Fail to push due to product missing on RHSM

        result = self._push_to_community(self._data_to_upload(enriched_push_items))

        # process result for failures
        failed = False
        for r in result:
            if r.get("state", "") != State.PUSHED:
                failed = True
            else:
                # Store the successful build ID for future evaluation if needed
                build_id = r["push_item"].build_info.id
                self.builds_borg.processed_builds.add(build_id)

        if not allow_empty_targets and len(result) == 0:
            log.error("No push item was processed.")
            failed = True

        # send to collector
        if collect_results:
            log.info("Collecting results")
            self.collect_push_result(result)

        if failed:
            log.error("Community VM push failed")
        else:
            log.info("Community VM push completed")
        if not self._SKIPPED and (allow_empty_targets and not result):
            self._SKIPPED = True
        return RUN_RESULT(not failed, self._SKIPPED, result)
