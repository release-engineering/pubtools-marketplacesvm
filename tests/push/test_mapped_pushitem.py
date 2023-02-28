# SPDX-License-Identifier: GPL-3.0-or-later
from typing import Any, Dict

import pytest
from pushsource import AmiPushItem, VHDPushItem
from starmap_client.models import Destination, QueryResponse

from pubtools._marketplacesvm.tasks.push.items import MappedVMIPushItem


def test_mapped_item_properties(
    ami_push_item: AmiPushItem,
    vhd_push_item: VHDPushItem,
    starmap_query_aws: QueryResponse,
    starmap_query_azure: QueryResponse,
) -> None:
    """Ensure the MappedVMIPushItem properties return the expected values."""
    items = [
        (ami_push_item, starmap_query_aws),
        (vhd_push_item, starmap_query_azure),
    ]

    for push_item, starmap_response in items:
        mapped_item = MappedVMIPushItem(push_item, starmap_response.clouds)

        # -- Test Property: state
        assert mapped_item.state == "PENDING"  # Default from Source

        # Test updating the state
        mapped_item.state = "TEST"
        assert mapped_item._push_item.state == "TEST"

        # Test invalid state
        expected_err = "Expected to receive a string for state, got: <class 'list'>"
        with pytest.raises(TypeError, match=expected_err):
            mapped_item.state = []  # type: ignore

        # -- Test Property: marketplaces
        assert mapped_item.marketplaces == list(starmap_response.clouds.keys())

        # -- Test Property: destinations
        expected_destinations = []
        for mkt in mapped_item.marketplaces:
            expected_destinations.extend(starmap_response.clouds[mkt])
        assert mapped_item.destinations == expected_destinations

        # -- Test Property: meta
        expected_meta = {}
        for dest in mapped_item.destinations:
            if dest.meta:
                expected_meta.update({k: v for k, v in dest.meta.items()})
        assert mapped_item.meta == expected_meta

        # -- Test some attributes mapping
        push_item = mapped_item.push_item
        assert push_item.dest == mapped_item.destinations
        assert push_item.release.arch == "x86_64"

        # -- Test wrapped _push_item changes
        assert mapped_item._push_item == mapped_item.push_item


def test_mapped_item_fills_missing_attributes(
    ami_push_item: AmiPushItem, starmap_response_aws: Dict[str, Any]
) -> None:
    """Ensure the wrapped PushItem get its attributes filled from metadata."""
    fields = [
        "description",
        "region",
        "sriov_net_support",
        "virtualization",
        "volume",
    ]
    for f in fields:
        # The incoming push item shouldn't have all attributes set
        assert not getattr(ami_push_item, f, None)

        # Define the missing fields in StArMap response for next test
        starmap_response_aws["mappings"]["aws-na"][0]["meta"].update({f: f})

    # Build the mapped item
    starmap_response = QueryResponse.from_json(starmap_response_aws)
    mapped_item = MappedVMIPushItem(ami_push_item, starmap_response.clouds)

    # Ensure the missing fields were mapped
    for f in fields:
        assert getattr(mapped_item.push_item, f) == f


def test_get_metadata_for_mapped_item(
    vhd_push_item: VHDPushItem, starmap_query_azure: QueryResponse
) -> None:
    mapped_item = MappedVMIPushItem(vhd_push_item, starmap_query_azure.clouds)

    # Test existing destinations
    for dest in starmap_query_azure.clouds["azure-na"]:
        assert mapped_item.get_metadata_for_mapped_item(dest) == dest.meta

    # Test unknown destination
    dest = Destination.from_json(
        {
            "destination": "foo/bar",
            "overwrite": True,
            "architecture": "x86_64",
        }
    )
    assert mapped_item.get_metadata_for_mapped_item(dest) == {}
