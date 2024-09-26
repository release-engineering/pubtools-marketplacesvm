# SPDX-License-Identifier: GPL-3.0-or-later
import pytest
from attrs import evolve
from pushsource import AmiPushItem
from starmap_client.models import BillingCodeRule, Destination

from pubtools._marketplacesvm.tasks.community_push.items import (
    _fix_arm64_arch,
    _get_push_item_public_image,
    _set_push_item_billing_code,
)


@pytest.mark.parametrize("product", ["RHEL_HA", "SAP"])
def test_get_push_item_public_image(product: str, ami_push_item: AmiPushItem) -> None:
    release = ami_push_item.release
    release = evolve(release, product=product, type="beta")
    pi = evolve(ami_push_item, release=release)

    res = _get_push_item_public_image(pi)

    assert res.public_image is False


def test_set_push_item_billing_code_no_name(ami_push_item: AmiPushItem) -> None:
    bcode = {
        "sample-hourly": BillingCodeRule.from_json(
            {
                "codes": ["bp-6fa54006"],
                "image_name": "sample_product",
                "image_types": ["hourly"],
            }
        )
    }

    dst = Destination.from_json(
        {
            "destination": "fake-region-hourly",
            "meta": {"billing-code-config": bcode},
            "overwrite": False,
            "restrict_version": False,
        }
    )

    res = _set_push_item_billing_code(ami_push_item, dst, bcode)

    res_bcode = res.billing_codes
    assert res_bcode.name == "Hourly2"


def test_rename_aarch64_to_arm64(ami_push_item: AmiPushItem) -> None:
    release = ami_push_item.release
    release = evolve(release, arch="aarch64")
    ami_push_item = evolve(ami_push_item, release=release)

    pi = _fix_arm64_arch(ami_push_item)

    assert pi.release.arch == "arm64"
