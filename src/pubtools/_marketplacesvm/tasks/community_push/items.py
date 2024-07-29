import logging
import os
from typing import Any, Dict, Optional

from attrs import evolve
from pushsource import AmiBillingCodes, AmiPushItem, AmiRelease
from starmap_client.models import Destination

BILLING_CODES_NAME_MAPPING = {
    "hourly": "Hourly2",
    "access": "Access2",
    "marketplace": "Marketplace",
}

log = logging.getLogger("pubtools.marketplacesvm")


def _get_push_item_region_type(push_item: AmiPushItem, destination: Destination) -> AmiPushItem:
    region, image_type = destination.destination.rsplit("-", 1)
    return evolve(push_item, region=region, type=image_type)


def _get_push_item_billing_code(push_item: AmiPushItem, destination: Destination) -> AmiPushItem:
    # The billing code config should be provided by StArMap
    billing_code_config: Optional[Dict[str, Any]] = destination.meta.get("billing-code-config")
    if not billing_code_config:
        raise RuntimeError(
            "No billing code configuration provided for %s on %s.",
            push_item.name,
            destination.destination,
        )

    # Auxiliary functions
    def is_match(bc_conf_item: Dict[str, Any], image_filename: str, image_type: str) -> bool:
        return all(
            [
                image_filename.startswith(bc_conf_item["image_name"]),
                image_type in bc_conf_item["image_types"],
            ]
        )

    def billing_code_name(bc_conf_item: Dict[str, Any], image_type: str) -> str:
        bc_name = bc_conf_item.get("name")
        if bc_name is None:
            bc_name = BILLING_CODES_NAME_MAPPING[image_type]
        return bc_name

    # Main
    out_codes = []
    out_name = None

    for bc_conf_item in billing_code_config.values():
        if is_match(bc_conf_item, os.path.basename(push_item.src), push_item.type):
            out_codes.extend(bc_conf_item["codes"])
            if out_name is None:
                out_name = billing_code_name(bc_conf_item, push_item.type)
    if out_name:
        codes = {"codes": out_codes, "name": out_name}
        push_item = evolve(push_item, billing_codes=AmiBillingCodes._from_data(codes))

    return push_item


def _get_push_item_public_image(push_item: AmiPushItem) -> AmiPushItem:
    def is_public_image(image_type: str, release: AmiRelease) -> bool:
        if image_type != "hourly":
            # Only the hourly images should be shared publicly since they are the only
            # type to charge an additional Red Hat fee.
            # http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/sharingamis-intro.html
            return False
        if release.product == "RHEL_HA" and release.type == "beta":
            # HighAvailability images are expected to be released publicly only during GA.
            # For Beta releases, they are expected to stay shared only with selected QE accounts.
            return False
        if release.product == "SAP":
            # SAP (resp. SAPHANA) images are expected to be released via Marketplace,
            # so for SAP, not even the hourly images are expected to be released publicly.
            return False
        return True

    return evolve(push_item, public_image=is_public_image(push_item.type, push_item.release))


def _get_push_item_rhsm_provider(push_item: AmiPushItem, destination: Destination) -> AmiPushItem:
    # The idea here is to write the RHSM "provider" name into the AmiPush item so we won't
    # need to have it passed by command line.
    #
    # However, since AmiPushItem doesn't have an attribute like "provider" or "provider_name"
    # and it seems like to be cumbersome adding it upstream just for this use case we'll borrow
    # a property used for marketplace but not for community AMIs named `marketplace_entity_type`
    # and use it to hold the RHSM provider name for this workflow.
    provider_name = destination.provider or "AWS"  # Defaults to "AWS" like the pubtools-ami CMD arg
    return evolve(push_item, marketplace_entity_type=provider_name)


def _update_destination(push_item: AmiPushItem, destination: Destination) -> AmiPushItem:
    return evolve(push_item, dest=[destination.destination])


def _fix_arm64_arch(push_item: AmiPushItem) -> AmiPushItem:
    # RHSM doesn't accept the value `aarch64` so we must rename it to `arm64`
    release: AmiRelease = push_item.release
    if release.arch.lower() == "aarch64":
        release = evolve(release, arch="arm64")
        push_item = evolve(push_item, release=release)
    return push_item


def enrich_push_item(
    push_item: AmiPushItem, destination: Destination, beta: bool, require_bc: bool = True
) -> AmiPushItem:
    """
    Set the missing push item attributes required for community workflow.

    Args:
        push_item:
            The push item to enrich with the missing values
        destination:
            The destination with all required information to enrich the push item.
        beta:
            Whether the release type is "beta" or not ("ga")
        require_bc:
            Whether the billing_codes are required (True) or not (False).
            Defaults to True.
    Returns:
        The enriched push item for community workflow.
    """
    # Usually the missing attributes for the community workflow at this point are:
    # - region
    # - type: "hourly" or "access"
    # - billing_codes
    # - public_image
    pi = _get_push_item_region_type(push_item, destination)
    if require_bc:
        pi = _get_push_item_billing_code(pi, destination)
    else:
        log.warning("BILLING CODES REQUIREMENT IS CURRENTLY DISABLED!")
    pi = _get_push_item_rhsm_provider(pi, destination)
    pi = _get_push_item_public_image(pi)

    # Rename aarch64 to arm64 if needed
    pi = _fix_arm64_arch(pi)

    # Set the release type
    rel_type = "beta" if beta else "ga"
    rel = evolve(pi.release, type=rel_type)
    pi = evolve(pi, release=rel)

    # Now we need to convert the "dest" from "List[Destination]" into "List[str]"
    # by just keeping the desired destinations and getting rid of everything else
    pi = _update_destination(pi, destination)
    return pi
