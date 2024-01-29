# SPDX-License-Identifier: GPL-3.0-or-later
import pytest
from attrs import evolve
from pushsource import AmiPushItem
from starmap_client.models import Destination

from pubtools._marketplacesvm.tasks.community_push.items import (
    _get_push_item_billing_code,
    _get_push_item_public_image,
)


@pytest.mark.parametrize("product", ["RHEL_HA", "SAP"])
def test_get_push_item_public_image(product: str, ami_push_item: AmiPushItem) -> None:
    release = ami_push_item.release
    release = evolve(release, product=product, type="beta")
    pi = evolve(ami_push_item, release=release)

    res = _get_push_item_public_image(pi)

    assert res.public_image is False


def test_get_push_item_billing_code_no_name(ami_push_item: AmiPushItem) -> None:
    bcode = {
        "sample-hourly": {
            "codes": ["bp-6fa54006"],
            "image_name": "sample_product",
            "image_types": ["hourly"],
        }
    }

    dst = Destination.from_json(
        {
            "destination": "fake-region-hourly",
            "meta": {"billing-code-config": bcode},
            "overwrite": False,
            "stage_preview": False,
            "restrict_version": False,
        }
    )

    res = _get_push_item_billing_code(ami_push_item, dst)

    res_bcode = res.billing_codes
    assert res_bcode.name == "Hourly2"
