# SPDX-License-Identifier: GPL-3.0-or-later
from datetime import datetime
from typing import Any, Dict

import pytest
from attrs import asdict, evolve
from pushsource import (
    AmiAccessEndpointUrl,
    AmiPushItem,
    AmiRelease,
    AmiSecurityGroup,
    VHDPushItem,
    VMIRelease,
)
from starmap_client.models import Destination, QueryResponse

from pubtools._marketplacesvm.tasks.push.items import MappedVMIPushItem
from pubtools._marketplacesvm.tasks.push.items.ami import (
    aws_access_endpoint_url_converter,
    aws_security_groups_converter,
)


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

        # -- Test Property: tags
        expected_tags = {}
        for dest in mapped_item.destinations:
            if dest.tags:
                expected_tags.update(dest.tags)
        assert mapped_item.tags == expected_tags

        # -- Test some attributes mapping
        for mkt in starmap_response.clouds.keys():
            push_item = mapped_item.get_push_item_for_marketplace(mkt)
            assert push_item.dest == starmap_response.clouds[mkt]
            assert push_item.release.arch == "x86_64"

            # -- Test wrapped push_item changes
            assert mapped_item.push_item == mapped_item.get_push_item_for_marketplace(mkt)

        # -- Test invalid marketplace
        with pytest.raises(ValueError, match="No such marketplace foo"):
            mapped_item.get_push_item_for_marketplace("foo")

        with pytest.raises(ValueError, match="No such marketplace foo"):
            mapped_item.get_tags_for_marketplace("foo")


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
        for mkt in starmap_response.clouds.keys():
            assert getattr(mapped_item.get_push_item_for_marketplace(mkt), f) == f


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
            "restrict_version": False,
            "architecture": "x86_64",
        }
    )
    assert mapped_item.get_metadata_for_mapped_item(dest) == {}


def test_release_info_on_metadata_for_mapped_ami(
    ami_push_item: AmiPushItem, starmap_query_aws: QueryResponse
) -> None:
    release_info = {
        "product": "test-product",
        "date": "2023-12-12",
        "arch": "x86_64",
        "respin": 1,
        "version": "8.0",
        "base_product": "test-base-product",
        "base_version": "1.0",
        "variant": "Server",
        "type": "ga",
    }

    # Erase the previous data
    pi = evolve(
        ami_push_item, release=AmiRelease(arch="x86_64", product="foo", date="2023-11-11", respin=0)
    )

    # We simulate having the "release" dict on each Destination for StArMap response.
    for list_dest in starmap_query_aws.clouds.values():
        for dest in list_dest:
            dest.meta["release"] = release_info

    # Test whether the MappedVMIPushItem can return the inner push item with the proper release
    mapped_item = MappedVMIPushItem(pi, starmap_query_aws.clouds)

    # Pushsource converts the "date" to datetime so we must do the same here to validate
    release_info["date"] = datetime.strptime(str(release_info["date"]), "%Y-%m-%d")

    # Validate the release data
    for mkt in starmap_query_aws.clouds.keys():
        pi = mapped_item.get_push_item_for_marketplace(mkt)
        rel_obj = pi.release

        assert isinstance(rel_obj, AmiRelease)
        assert asdict(rel_obj) == release_info


def test_release_info_on_metadata_for_mapped_vhd(
    vhd_push_item: VHDPushItem, starmap_query_aws: QueryResponse
) -> None:
    release_info = {
        "product": "test-product",
        "date": "2023-11-11",
        "arch": "x86_64",
        "respin": 2,
        "version": "8.0",
        "base_product": "test-base-product",
        "base_version": "1.0",
        "variant": "Server",
        "type": "ga",
    }

    # Erase the previous data
    pi = evolve(
        vhd_push_item, release=VMIRelease(arch="x86_64", product="foo", date="2023-11-11", respin=0)
    )

    # We simulate having the "release" dict on each Destination for StArMap response.
    for list_dest in starmap_query_aws.clouds.values():
        for dest in list_dest:
            dest.meta["release"] = release_info

    # Test whether the MappedVMIPushItem can return the inner push item with the proper release
    mapped_item = MappedVMIPushItem(pi, starmap_query_aws.clouds)

    # Pushsource converts the "date" to datetime so we must do the same here to validate
    release_info["date"] = datetime.strptime(str(release_info["date"]), "%Y-%m-%d")

    # Validate the release data
    for mkt in starmap_query_aws.clouds.keys():
        pi = mapped_item.get_push_item_for_marketplace(mkt)
        rel_obj = pi.release

        assert isinstance(rel_obj, VMIRelease)
        assert asdict(rel_obj) == release_info


def test_get_tags_for_mapped_item(
    vhd_push_item: VHDPushItem, starmap_query_azure: QueryResponse
) -> None:
    mapped_item = MappedVMIPushItem(vhd_push_item, starmap_query_azure.clouds)

    # Test existing destinations
    for dest in starmap_query_azure.clouds["azure-na"]:
        assert mapped_item.get_tags_for_mapped_item(dest) == dest.tags or {}

    # Test unknown destination
    dest = Destination.from_json(
        {
            "destination": "foo/bar",
            "overwrite": True,
            "restrict_version": False,
            "architecture": "x86_64",
        }
    )
    assert mapped_item.get_tags_for_mapped_item(dest) == {}


def test_get_tags_for_marketplace(
    vhd_push_item: VHDPushItem, starmap_query_azure: QueryResponse
) -> None:
    expected_tags = {"key1": "value1", "key2": "value2"}
    mapped_item = MappedVMIPushItem(vhd_push_item, starmap_query_azure.clouds)

    assert mapped_item.get_tags_for_marketplace("azure-na") == expected_tags


def test_register_converter() -> None:
    def func(x: Any) -> str:
        return str(x)

    assert not MappedVMIPushItem._CONVERTER_HANDLERS.get("test")

    MappedVMIPushItem.register_converter("test", func)

    assert MappedVMIPushItem._CONVERTER_HANDLERS.get("test") == func


def test_converter_aws_securitygroups() -> None:
    fake_sec_group = {
        "from_port": 1234,
        "ip_protocol": "tcp",
        "ip_ranges": ["0.0.0.0"],
        "to_port": 4321,
    }

    res = aws_security_groups_converter([fake_sec_group])

    assert isinstance(res[0], AmiSecurityGroup)
    assert asdict(res[0]) == fake_sec_group


def test_converter_aws_access_endpoint_url_converter() -> None:
    fake_access_endpoint_url = {'port': 9990, 'protocol': 'http'}

    res = aws_access_endpoint_url_converter(fake_access_endpoint_url)

    assert isinstance(res, AmiAccessEndpointUrl)
    assert asdict(res) == fake_access_endpoint_url
