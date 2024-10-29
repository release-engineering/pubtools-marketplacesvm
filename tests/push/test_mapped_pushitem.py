# SPDX-License-Identifier: GPL-3.0-or-later
from datetime import datetime
from typing import Any, Dict, List, Tuple

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
from starmap_client.models import Destination, QueryResponseEntity

from pubtools._marketplacesvm.tasks.push.items import MappedVMIPushItemV2
from pubtools._marketplacesvm.tasks.push.items.ami import (
    aws_access_endpoint_url_converter,
    aws_security_groups_converter,
)


def test_mapped_item_properties(
    ami_push_item: AmiPushItem,
    vhd_push_item: VHDPushItem,
    starmap_query_aws: QueryResponseEntity,
    starmap_query_azure: QueryResponseEntity,
) -> None:
    """Ensure the MappedVMIPushItemV2 properties return the expected values."""
    items: List[Tuple[VHDPushItem, QueryResponseEntity]] = [
        (ami_push_item, starmap_query_aws),
        (vhd_push_item, starmap_query_azure),
    ]

    for push_item, starmap_response in items:
        mapped_item = MappedVMIPushItemV2(push_item, starmap_response)

        # -- Test Property: marketplaces
        assert mapped_item.marketplaces == starmap_response.account_names

        # -- Test Property: destinations
        expected_destinations = []
        for _, mrobj in starmap_response.mappings.items():
            expected_destinations.extend(mrobj.destinations)
        assert mapped_item.destinations == expected_destinations

        # -- Test Property: tags
        expected_tags = {}
        for dest in mapped_item.destinations:
            if dest.tags:
                expected_tags.update(dest.tags)
        assert mapped_item.tags == expected_tags

        # -- Test some attributes mapping
        for mkt in starmap_response.account_names:
            push_item = mapped_item.get_push_item_for_marketplace(mkt)
            assert push_item.dest == starmap_response.mappings[mkt].destinations
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
        starmap_response_aws["mappings"]["aws-na"]["destinations"][0]["meta"].update({f: f})

    # Build the mapped item
    starmap_response = QueryResponseEntity.from_json(starmap_response_aws)
    mapped_item = MappedVMIPushItemV2(ami_push_item, starmap_response)

    # Ensure the missing fields were mapped
    for f in fields:
        for mkt in starmap_response.account_names:
            assert getattr(mapped_item.get_push_item_for_marketplace(mkt), f) == f


def test_get_metadata_for_mapped_item(
    vhd_push_item: VHDPushItem, starmap_query_azure: QueryResponseEntity
) -> None:
    mapped_item = MappedVMIPushItemV2(vhd_push_item, starmap_query_azure)

    # Test existing destinations
    for dest in starmap_query_azure.mappings["azure-na"].destinations:
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
    ami_push_item: AmiPushItem, starmap_query_aws: QueryResponseEntity
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
    for mapping in starmap_query_aws.all_mappings:
        for dest in mapping.destinations:
            dest.meta["release"] = release_info

    # Test whether the MappedVMIPushItemV2 can return the inner push item with the proper release
    mapped_item = MappedVMIPushItemV2(pi, starmap_query_aws)

    # Pushsource converts the "date" to datetime so we must do the same here to validate
    release_info["date"] = datetime.strptime(str(release_info["date"]), "%Y-%m-%d")

    # Validate the release data
    for mkt in starmap_query_aws.account_names:
        pi = mapped_item.get_push_item_for_marketplace(mkt)
        rel_obj = pi.release

        assert isinstance(rel_obj, AmiRelease)
        assert asdict(rel_obj) == release_info


def test_release_info_on_metadata_for_mapped_vhd(
    vhd_push_item: VHDPushItem, starmap_query_aws: QueryResponseEntity
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
    for mapping in starmap_query_aws.all_mappings:
        for dest in mapping.destinations:
            dest.meta["release"] = release_info

    # Test whether the MappedVMIPushItemV2 can return the inner push item with the proper release
    mapped_item = MappedVMIPushItemV2(pi, starmap_query_aws)

    # Pushsource converts the "date" to datetime so we must do the same here to validate
    release_info["date"] = datetime.strptime(str(release_info["date"]), "%Y-%m-%d")

    # Validate the release data
    for mkt in starmap_query_aws.account_names:
        pi = mapped_item.get_push_item_for_marketplace(mkt)
        rel_obj = pi.release

        assert isinstance(rel_obj, VMIRelease)
        assert asdict(rel_obj) == release_info


def test_get_tags_for_mapped_item(
    vhd_push_item: VHDPushItem, starmap_query_azure: QueryResponseEntity
) -> None:
    mapped_item = MappedVMIPushItemV2(vhd_push_item, starmap_query_azure)

    # Test existing destinations
    for dest in starmap_query_azure.mappings["azure-na"].destinations:
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
    vhd_push_item: VHDPushItem, starmap_query_azure: QueryResponseEntity
) -> None:
    expected_tags = {"key1": "value1", "key2": "value2"}
    mapped_item = MappedVMIPushItemV2(vhd_push_item, starmap_query_azure)

    assert mapped_item.get_tags_for_marketplace("azure-na") == expected_tags


def test_get_ami_template_for_marketplace(
    ami_push_item: AmiPushItem, starmap_query_aws: QueryResponseEntity
) -> None:
    mapped_item = MappedVMIPushItemV2(ami_push_item, starmap_query_aws)

    # Test existing destinations
    for dest in starmap_query_aws.mappings["aws-na"].destinations:
        avt = mapped_item.get_ami_version_template_for_mapped_item(dest)
        assert avt == dest.ami_version_template or ""

    # Test unknown destination
    dest = Destination.from_json(
        {
            "destination": "foo/bar",
            "overwrite": True,
            "restrict_version": False,
            "architecture": "x86_64",
        }
    )
    assert mapped_item.get_ami_version_template_for_mapped_item(dest) == ""


def test_register_converter() -> None:
    def func(x: Any) -> str:
        return str(x)

    assert not MappedVMIPushItemV2._CONVERTER_HANDLERS.get("test")

    MappedVMIPushItemV2.register_converter("test", func)

    assert MappedVMIPushItemV2._CONVERTER_HANDLERS.get("test") == func


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
