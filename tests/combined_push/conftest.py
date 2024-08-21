# SPDX-License-Identifier: GPL-3.0-or-later
from datetime import datetime
from typing import Any, Dict

import pytest
from pushsource import AmiPushItem, AmiRelease, KojiBuildInfo, VHDPushItem, VMIRelease
from starmap_client.models import QueryResponse

from pubtools._marketplacesvm.tasks.combined_push.command import CombinedVMPush
from pubtools._marketplacesvm.tasks.community_push.command import CommunityVMPush
from pubtools._marketplacesvm.tasks.push.command import MarketplacesVMPush


@pytest.fixture(scope="session")
def monkeysession():
    from _pytest.monkeypatch import MonkeyPatch

    mpatch = MonkeyPatch()
    yield mpatch
    mpatch.undo()


@pytest.fixture(scope="session", autouse=True)
def combined_vm_push(monkeysession: pytest.MonkeyPatch) -> None:
    """Set a single-thread for MarketplacesVMPush, CommunityVMPush and CombinedVMPush."""
    monkeysession.setattr(MarketplacesVMPush, '_REQUEST_THREADS', 1)
    monkeysession.setattr(MarketplacesVMPush, '_PROCESS_THREADS', 1)
    monkeysession.setattr(CommunityVMPush, '_REQUEST_THREADS', 1)
    monkeysession.setattr(CommunityVMPush, '_PROCESS_THREADS', 1)

    monkeysession.setattr(CombinedVMPush, '_REQUEST_THREADS', 1)


@pytest.fixture
def release_params() -> Dict[str, Any]:
    return {
        "product": "sample_product",
        "version": "7.0",
        "arch": "x86_64",
        "respin": 1,
        "date": datetime.strptime("2023-12-12", "%Y-%m-%d"),
        "base_product": "sample_base",
        "base_version": "1.0",
        "variant": "variant",
        "type": "ga",
    }


@pytest.fixture
def push_item_params() -> Dict[str, str]:
    return {
        "name": "name",
        "src": "/foo/bar/sample_product_test.raw",
        "description": "",
        "build_info": KojiBuildInfo(id=1, name="test-build", version="7.0", release="20230101"),
    }


@pytest.fixture
def vhd_push_item(release_params: Dict[str, Any], push_item_params: Dict[str, str]) -> VHDPushItem:
    """Return a minimal VHDPushItem."""
    release = VMIRelease(**release_params)
    push_item_params.update({"name": "vhd_pushitem", "release": release})
    return VHDPushItem(**push_item_params)


@pytest.fixture
def ami_push_item(release_params: Dict[str, Any], push_item_params: Dict[str, str]) -> AmiPushItem:
    """Return a minimal AmiPushItem."""
    release = AmiRelease(**release_params)
    push_item_params.update({"name": "ami_pushitem", "release": release})
    return AmiPushItem(**push_item_params)


@pytest.fixture
def starmap_response_aws_marketplace() -> Dict[str, Any]:
    """Return the dictionary corresponding to a marketplace AWS response."""
    return {
        "mappings": {
            "aws-na": [
                {
                    "architecture": "x86_64",
                    "destination": "ffffffff-ffff-ffff-ffff-ffffffffffff",
                    "overwrite": True,
                    "restrict_version": False,
                    "meta": {"tag1": "aws-na-value1", "tag2": "aws-na-value2"},
                    "tags": {"key1": "value1", "key2": "value2"},
                }
            ],
            "aws-emea": [
                {
                    "architecture": "x86_64",
                    "destination": "00000000-0000-0000-0000-000000000000",
                    "overwrite": True,
                    "restrict_version": False,
                    "meta": {"tag1": "aws-emea-value1", "tag2": "aws-emea-value2"},
                    "tags": {"key3": "value3", "key4": "value4"},
                }
            ],
        },
        "name": "sample-product",
        "workflow": "stratosphere",
    }


@pytest.fixture()
def starmap_ami_billing_config() -> Dict[str, Any]:
    return {
        "sample-hourly": {
            "name": "Hourly2",
            "codes": ["bp-6fa54006"],
            "image_name": "sample_product",
            "image_types": ["hourly"],
        },
        "sample-access": {
            "name": "Access2",
            "codes": ["bp-63a5400a"],
            "image_name": "sample_product",
            "image_types": ["access"],
        },
    }


@pytest.fixture()
def starmap_ami_meta(release_params, starmap_ami_billing_config) -> Dict[str, Any]:
    return {
        "description": "Provided by Red Hat, Inc.",
        "virtualization": "hvm",
        "volume": "gp2",
        "root_device": "/dev/sda1",
        "sriov_net_support": "simple",
        "ena_support": True,
        "release": release_params,
        "billing-code-config": starmap_ami_billing_config,
        "accounts": {
            "default": "000000",
            "us-east-1": "121212",
        },
        "snapshot_accounts": {
            "default": "111111",
            "us-east-1": "121212",
        },
    }


@pytest.fixture
def starmap_response_aws_community(starmap_ami_meta) -> Dict[str, Any]:
    """Return the dictionary corresponding to a community AWS response."""
    destinations = [
        "us-east-1-hourly",
        "us-east-1-access",
        "us-east-2-hourly",
        "us-east-2-access",
        "us-west-1-hourly",
        "us-west-1-access",
        "us-west-2-hourly",
        "us-west-2-access",
    ]

    return {
        "mappings": {
            "aws_storage": [
                {
                    "architecture": "x86_64",
                    "destination": dest,
                    "overwrite": False,
                    "restrict_version": False,
                    "provider": "awstest",
                    "meta": starmap_ami_meta,
                    "tags": {"key1": "value1", "key2": "value2"},
                }
                for dest in destinations
            ],
        },
        "name": "sample_product",
        "workflow": "community",
    }


@pytest.fixture
def starmap_response_azure() -> Dict[str, Any]:
    """Return the dictionary corresponding to a marketplace Azure response."""
    return {
        "mappings": {
            "azure-na": [
                {
                    "architecture": "x86_64",
                    "destination": "destination_offer_main/plan1",
                    "overwrite": True,
                    "restrict_version": False,
                    "meta": {"tag1": "value1", "tag2": "value2"},
                    "tags": {"key1": "value1", "key2": "value2"},
                },
                {
                    "architecture": "x86_64",
                    "destination": "destination_offer_main/plan2",
                    "overwrite": False,
                    "restrict_version": False,
                    "meta": {"tag3": "value3", "tag4": "value5"},
                },
                {
                    "architecture": "x86_64",
                    "destination": "destination_offer_main/plan3",
                    "overwrite": False,
                    "restrict_version": False,
                },
            ]
        },
        "name": "sample-product",
        "workflow": "stratosphere",
    }


@pytest.fixture
def starmap_query_aws_marketplace(
    starmap_response_aws_marketplace: Dict[str, Any]
) -> QueryResponse:
    return QueryResponse.from_json(starmap_response_aws_marketplace)


@pytest.fixture
def starmap_query_aws_community(starmap_response_aws_community: Dict[str, Any]) -> QueryResponse:
    return QueryResponse.from_json(starmap_response_aws_community)


@pytest.fixture
def starmap_query_azure(starmap_response_azure: Dict[str, Any]) -> QueryResponse:
    return QueryResponse.from_json(starmap_response_azure)
