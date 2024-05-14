# SPDX-License-Identifier: GPL-3.0-or-later
from datetime import datetime
from typing import Any, Dict

import pytest
from attrs import evolve
from pushsource import AmiPushItem, AmiRelease, KojiBuildInfo
from starmap_client.models import QueryResponse

from pubtools._marketplacesvm.tasks.community_push.command import CommunityVMPush


@pytest.fixture(scope="session")
def monkeysession():
    from _pytest.monkeypatch import MonkeyPatch

    mpatch = MonkeyPatch()
    yield mpatch
    mpatch.undo()


@pytest.fixture(scope="session", autouse=True)
def marketplaces_vm_push(monkeysession: pytest.MonkeyPatch) -> None:
    """Set a single-thread for MarketplacesVMPush."""
    monkeysession.setattr(CommunityVMPush, '_REQUEST_THREADS', 1)
    monkeysession.setattr(CommunityVMPush, '_PROCESS_THREADS', 1)


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
        "build_info": KojiBuildInfo(name="test-build", version="7.0", release="20230101"),
    }


@pytest.fixture
def ami_push_item(release_params: Dict[str, Any], push_item_params: Dict[str, str]) -> AmiPushItem:
    """Return a minimal AmiPushItem."""
    release = AmiRelease(**release_params)
    # FIXME: the "type: hourly" should be removed later when it will get resolved from StArMap
    push_item_params.update({"name": "ami_pushitem", "release": release, "type": "hourly"})
    return AmiPushItem(**push_item_params)


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
def starmap_response_aws(starmap_ami_meta) -> Dict[str, Any]:
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
def starmap_query_aws(starmap_response_aws: Dict[str, Any]) -> QueryResponse:
    return QueryResponse.from_json(starmap_response_aws)


@pytest.fixture
def mapped_ami_push_item(
    ami_push_item: AmiPushItem, starmap_query_aws: QueryResponse
) -> AmiPushItem:
    destinations = []
    for _, dest_list in starmap_query_aws.clouds.items():
        for dest in dest_list:
            destinations.append(dest)
    return evolve(ami_push_item, dest=destinations)
