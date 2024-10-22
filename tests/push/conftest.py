# SPDX-License-Identifier: GPL-3.0-or-later
from datetime import datetime
from typing import Any, Dict

import pytest
from attrs import evolve
from pushsource import AmiPushItem, AmiRelease, KojiBuildInfo, VHDPushItem, VMIRelease
from starmap_client.models import QueryResponseEntity

from pubtools._marketplacesvm.tasks.push.command import MarketplacesVMPush


@pytest.fixture(scope="session")
def monkeysession():
    from _pytest.monkeypatch import MonkeyPatch

    mpatch = MonkeyPatch()
    yield mpatch
    mpatch.undo()


@pytest.fixture(scope="session", autouse=True)
def marketplaces_vm_push(monkeysession: pytest.MonkeyPatch) -> None:
    """Set a single-thread for MarketplacesVMPush."""
    monkeysession.setattr(MarketplacesVMPush, '_REQUEST_THREADS', 1)
    monkeysession.setattr(MarketplacesVMPush, '_PROCESS_THREADS', 1)


@pytest.fixture
def release_params() -> Dict[str, Any]:
    return {
        "product": "sample-product",
        "version": "7.0",
        "arch": "x86_64",
        "respin": 1,
        "date": datetime.now(),
    }


@pytest.fixture
def push_item_params() -> Dict[str, str]:
    return {
        "name": "name",
        "description": "",
        "build_info": KojiBuildInfo(name="test-build", version="7.0", release="20230101"),
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
def starmap_response_aws() -> Dict[str, Any]:
    return {
        "mappings": {
            "aws-na": {
                "destinations": [
                    {
                        "architecture": "x86_64",
                        "destination": "ffffffff-ffff-ffff-ffff-ffffffffffff",
                        "overwrite": True,
                        "restrict_version": False,
                        "meta": {"tag1": "aws-na-value1", "tag2": "aws-na-value2"},
                        "tags": {"key1": "value1", "key2": "value2"},
                        "ami_version_template": "{major}.{minor}.{patch}",
                    }
                ]
            },
            "aws-emea": {
                "destinations": [
                    {
                        "architecture": "x86_64",
                        "destination": "00000000-0000-0000-0000-000000000000",
                        "overwrite": True,
                        "restrict_version": False,
                        "meta": {"tag1": "aws-emea-value1", "tag2": "aws-emea-value2"},
                        "tags": {"key3": "value3", "key4": "value4"},
                    }
                ]
            },
        },
        "name": "sample-product",
        "workflow": "stratosphere",
        "cloud": "aws",
    }


@pytest.fixture
def starmap_response_azure() -> Dict[str, Any]:
    return {
        "mappings": {
            "azure-na": {
                "destinations": [
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
            }
        },
        "name": "sample-product",
        "workflow": "stratosphere",
        "cloud": "azure",
    }


@pytest.fixture
def starmap_query_aws(starmap_response_aws: Dict[str, Any]) -> QueryResponseEntity:
    return QueryResponseEntity.from_json(starmap_response_aws)


@pytest.fixture
def starmap_query_azure(starmap_response_azure: Dict[str, Any]) -> QueryResponseEntity:
    return QueryResponseEntity.from_json(starmap_response_azure)


@pytest.fixture
def mapped_ami_push_item(
    ami_push_item: AmiPushItem, starmap_query_aws: QueryResponseEntity
) -> AmiPushItem:
    destinations = []
    for _, map_rsp_obj in starmap_query_aws.mappings.items():
        destinations.extend(map_rsp_obj.destinations)
    return evolve(ami_push_item, dest=destinations)


@pytest.fixture
def mapped_vhd_push_item(
    vhd_push_item: VHDPushItem, starmap_query_azure: QueryResponseEntity
) -> VHDPushItem:
    destinations = []
    for _, map_rsp_obj in starmap_query_azure.mappings.items():
        destinations.append(map_rsp_obj.destinations)
    return evolve(vhd_push_item, dest=destinations)
