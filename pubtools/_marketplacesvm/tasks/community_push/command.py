# SPDX-License-Identifier: GPL-3.0-or-later
import json
import logging
import os
import sys
from typing import Any, Dict, Iterator, List, Optional, Union

from attrs import asdict, evolve
from more_executors import Executors
from pushsource import AmiPushItem, Source
from starmap_client.models import QueryResponse, Workflow

from ...services.rhsm import AwsRHSMClientService
from ..push import MarketplacesVMPush
from ..push.items import MappedVMIPushItem, State

log = logging.getLogger("pubtools.marketplacesvm")


class CommunityVMPush(MarketplacesVMPush, AwsRHSMClientService):
    """Upload an AMI to S3 and update RHSM."""

    _REQUEST_THREADS = int(os.environ.get("COMMUNITY_PUSH_REQUEST_THREADS", "5"))

    def __init__(self, *args, **kwargs):
        """Initialize the CommunityVMPush instance."""
        self._rhsm_products: Optional[List[Dict[str, Any]]] = None
        super(CommunityVMPush, self).__init__(*args, **kwargs)

    def _fail(self, *args, **kwargs):
        log.error(*args, **kwargs)
        sys.exit(30)

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
                    {"name": binfo.name, "version": binfo.version, "query_response": asdict(query)},
                    default=str,
                ),
            )
            item = MappedVMIPushItem(item, query.clouds)
            # TODO: Check in the upcoming storage-mapping format an analogue way to do this
            # if not item.destinations:
            #    log.info("Filtering out archive with no destinations: %s", item.push_item.src)
            #    continue
            mapped_items.append({"item": item, "starmap_query": query})
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

    def get_rhsm_product(self, product: str, image_type: str) -> Dict[str, Any]:
        """Retrieve a product info from RHSM for the specified product in metadata.

        Args:
            product (str): The product name
            image_type (str): The image type (hourly or access)

        Returns:
            The specified product info from RHSM.
        """
        # The rhsm prodcut should always be the product (short) plus
        # "_HOURLY" for hourly type images.
        image_type = image_type.upper()
        aws_provider_name = self.args.aws_provider_name
        if image_type == "HOURLY":
            product = product.upper() + "_" + image_type

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

    def in_rhsm(self, product: str, image_type: str) -> bool:
        """Check whether the product is present in rhsm for the provider.

        Args:
            product (str): The product name
            image_type (str): The image type (hourly or access)
            aws_provider_name (str): The AWS provider name

        Returns:
            True if the product is found in rhsm_products else False.
        """
        try:
            self.get_rhsm_product(product, image_type)
        except RuntimeError as er:
            log.error(er)
            return False
        return True

    def items_in_metadata_service(self, mapped_items: List[MappedVMIPushItem]):
        """Check for all the push_items whether they are in rhsm or not.

        Args:
            mapped_items:
                List of MappedVMIPushItem to check on RHSM.

        Returns:
            False if any of item is missing in RHSM else True.
        """
        verified = True
        for item in mapped_items:
            # Since the StArMap "meta" should be the same for all destinations
            # we can retrieve a push item from any marketplace at this moment
            # just to have all properties loaded before checking on RHSM
            pi = item.get_push_item_for_marketplace(item.marketplaces[0])
            if not self.in_rhsm(pi.release.product, pi.type):
                log.error(
                    "Pre-push check in metadata service failed for %s at %s",
                    pi.name,
                    pi.src,
                )
                item.push_item = evolve(pi, state="INVALIDFILE")
                verified = False
        return verified

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

    def add_args(self):
        """Include the required CLI arguments for CommunityVMPush."""
        super(CommunityVMPush, self).add_args()

        self.parser.add_argument(
            "--aws-provider-name",
            help="AWS provider e.g. AWS, ACN (AWS China), AGOV (AWS US Gov)",
            default="AWS",
        )

    def run(self):
        """Execute the community_push command workflow."""
        mapped_items = self.mapped_items
        if not self.items_in_metadata_service([x["item"] for x in mapped_items]):
            self._fail("Pre-push verification of push items in metadata service failed")

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
            self._fail("Community VM push failed")

        # FIXME: Remove the coverage skip when the command gets properly implemented
        log.info("Community VM push completed")  # pragma: no cover
