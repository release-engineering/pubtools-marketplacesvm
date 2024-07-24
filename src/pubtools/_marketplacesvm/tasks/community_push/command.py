# SPDX-License-Identifier: GPL-3.0-or-later
import json
import logging
import os
from collections import namedtuple
from typing import Any, Dict, Iterator, List, Optional

from attrs import asdict, evolve
from more_executors import Executors
from pushsource import AmiPushItem, Source, VMIPushItem
from requests import HTTPError, Response
from starmap_client.models import Workflow

from pubtools._marketplacesvm.tasks.community_push.items import enrich_push_item

from ...cloud_providers.aws import name_from_push_item
from ...services.rhsm import AwsRHSMClientService
from ...task import RUN_RESULT
from ..push import MarketplacesVMPush
from ..push.items import MappedVMIPushItem, State

log = logging.getLogger("pubtools.marketplacesvm")

SharingAccounts = Dict[str, List[str]]
PushItemAndSA = namedtuple("PushItemAndSA", ["push_items", "sharing_accounts"])
EnrichedPushItem = Dict[str, PushItemAndSA]


class CommunityVMPush(MarketplacesVMPush, AwsRHSMClientService):
    """Upload an AMI to S3 and update RHSM."""

    _REQUEST_THREADS = int(os.environ.get("COMMUNITY_PUSH_REQUEST_THREADS", "5"))
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
                    yield item

    @property
    def mapped_items(self) -> List[MappedVMIPushItem]:  # type: ignore [override]
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
            if query:
                log.info(
                    "starmap query returned for %s : %s ",
                    item.name,
                    json.dumps(
                        {
                            "name": binfo.name,
                            "version": binfo.version,
                            "query_response": asdict(query),
                        },
                        default=str,
                    ),
                )
                item = MappedVMIPushItem(item, query.clouds)
                mapped_items.append(item)
            else:
                self._SKIPPED = True
                log.error(f"No mappings found for {binfo.name}")
        return mapped_items

    @property
    def rhsm_products(self) -> List[Dict[str, Any]]:
        """List of products/image groups for AWS provider."""
        if self._rhsm_products is None:
            response = self.rhsm_client.aws_products().result()
            self._rhsm_products = response.json()["body"]
            prod_names = [
                "%s(%s)" % (p["name"], p["providerShortName"]) for p in self._rhsm_products
            ]
            log.debug(
                "%s Products(AWS provider) in rhsm: %s",
                len(prod_names),
                ", ".join(sorted(prod_names)),
            )
        return self._rhsm_products

    def get_rhsm_product(
        self, product: str, image_type: str, aws_provider_name: str
    ) -> Dict[str, Any]:
        """Retrieve a product info from RHSM for the specified product in metadata.

        Args:
            product (str): The product name
            image_type (str): The image type (hourly or access)
            aws_provider_name (str): The provider name for RHSM

        Returns:
            The specified product info from RHSM.
        """
        # The rhsm prodcut should always be the product (short) plus
        # "_HOURLY" for hourly type images.
        image_type = image_type.upper()
        if image_type == "HOURLY":
            product = product + "_" + image_type

        log.debug(
            "Searching for product %s for provider %s in rhsm",
            product,
            aws_provider_name,
        )
        for rhsm_product in self.rhsm_products:
            if (
                rhsm_product["name"] == product
                and rhsm_product["providerShortName"] == aws_provider_name  # noqa: W503
            ):
                return rhsm_product

        raise RuntimeError("Product not in RHSM: %s" % product)

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

    def _get_sharing_accounts(self, mapped_item: MappedVMIPushItem) -> SharingAccounts:
        """Return the sharing acconts configuration when provided by StArMap.

        Args:
            mapped_item (MappedVMIPushItem): The mapped item to retrieve the accounts from meta.
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
        def set_accounts(
            acct_name: str, mapped_item: MappedVMIPushItem, acct_dict: Dict[str, List[str]]
        ) -> None:
            accts = mapped_item.meta.get(acct_name)
            if not accts:
                log.warning(
                    "No %s definition in StArMap, leaving the defaults from credentials.", acct_name
                )
                return

            log.info("Loading %s from StArMap.", acct_name)
            if isinstance(accts, dict):
                combined_accts = []
                for _, accounts in accts.items():  # expected format: Dict[str, List[str]]
                    combined_accts.append(accounts)
                    log.debug("Loaded \"%s\": \"%s\".", acct_name, accounts)
                acct_dict.setdefault(acct_name, combined_accts)
            elif isinstance(accts, list):  # expected format: List[str]
                log.debug("Loaded the following accounts as \"%s\": %s", acct_name, accts)
                acct_dict.setdefault(acct_name, accts)

        result: SharingAccounts = {}
        set_accounts("accounts", mapped_item, result)
        set_accounts("sharing_accounts", mapped_item, result)
        set_accounts("snapshot_accounts", mapped_item, result)
        return result

    def enrich_mapped_items(self, mapped_items: List[MappedVMIPushItem]) -> List[EnrichedPushItem]:
        """Load all missing information for each mapped item.

        It returns a list of dictionaries which contains the storage account and
        the push items for each account.

        Args:
            mapped_items (List[MappedVMIPushItem]): The list of mapped items.

        Returns:
            List[EnrichedPushItem]: List of resulting enriched push items.
        """
        result: List[EnrichedPushItem] = []
        for mapped_item in mapped_items:
            sharing_accounts = self._get_sharing_accounts(mapped_item)
            account_dict: EnrichedPushItem = {}
            for storage_account, destinations in mapped_item.clouds.items():
                log.info("Processing the storage account %s", storage_account)

                enriched_pi_list: List[AmiPushItem] = []
                pi = mapped_item.get_push_item_for_marketplace(storage_account)
                log.debug("Mapped push item for %s: %s", storage_account, pi)

                for dest in destinations:
                    epi = enrich_push_item(
                        pi, dest, beta=self.args.beta, require_bc=self._REQUIRE_BC
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
                    enriched_pi_list.append(epi)
                account_dict[storage_account] = PushItemAndSA(enriched_pi_list, sharing_accounts)
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
            log.info(
                "Uploading %s to region %s (type: %s, ship: %s)",
                push_item.src,
                push_item.region,
                push_item.type,
                ship,
            )
            accounts = kwargs.get("accounts") or kwargs.get("sharing_accounts")
            snapshot_accounts = kwargs.get("snapshot_accounts")
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
            for push_items, _ in enriched_item.values():
                if not self.items_in_metadata_service(push_items):
                    log.error("Pre-push verification of push items in metadata service failed")
                    return False
        return True

    def _push_to_community(self, enriched_push_item: EnrichedPushItem) -> List[Dict[str, Any]]:
        """
        Perform the whole community workflow to upload the AMI and update RHSM.

        Args:
            enriched_push_item
                Dictionary with the storage account name and the push items.
        Returns:
            Dictionary with the resulting operation for the Collector service.
        """
        result = []
        for storage_account, push_items_and_sa in enriched_push_item.items():
            # Setup the threading
            to_await = []
            out_pi = []
            push_items = push_items_and_sa.push_items
            executor = Executors.thread_pool(
                name="pubtools-marketplacesvm-community-push-regions",
                max_workers=min(max(len(push_items), 1), self._PROCESS_THREADS),
            )

            # Prepare the sharing accounts
            sharing_accts: SharingAccounts = push_items_and_sa.sharing_accounts
            additional_args = {}
            extra_args = ["accounts", "sharing_accounts", "snapshot_accounts"]
            for arg in extra_args:
                content = sharing_accts.get(arg)
                if content:
                    additional_args[arg] = content

            # Upload the push items in parallel
            log.info("Uploading to the storage account %s", storage_account)
            for pi in push_items:
                to_await.append(
                    executor.submit(self._upload, storage_account, pi, **additional_args)
                )

            # Wait for all results
            for f_out in to_await:
                out_pi.append(f_out.result())

            # Append the data for collection
            for pi in out_pi:
                result.append(
                    {
                        "push_item": pi,
                        "state": pi.state,
                        "image_id": pi.image_id,
                        "image_name": name_from_push_item(pi),
                    }
                )
        return result

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

        executor = Executors.thread_pool(
            name="pubtools-marketplacesvm-community-push",
            max_workers=min(max(len(enriched_push_items), 1), self._REQUEST_THREADS),
        )

        to_await = []
        result = []
        for enriched_item in enriched_push_items:
            to_await.append(executor.submit(self._push_to_community, enriched_item))

        # waiting for results
        for f_out in to_await:
            result.extend(f_out.result())

        # process result for failures
        failed = False
        for r in result:
            if r.get("state", "") != State.PUSHED:
                failed = True

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
