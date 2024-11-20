# SPDX-License-Identifier: GPL-3.0-or-later
from datetime import datetime
from typing import Any, Dict, List

import pytest
from pushsource import (
    AmiAccessEndpointUrl,
    AmiPushItem,
    AmiRelease,
    AmiSecurityGroup,
    KojiBuildInfo,
    VHDPushItem,
    VMIRelease,
)

from pubtools._marketplacesvm.tasks.delete.command import VMDelete


@pytest.fixture(scope="session")
def monkeysession():
    from _pytest.monkeypatch import MonkeyPatch

    mpatch = MonkeyPatch()
    yield mpatch
    mpatch.undo()


@pytest.fixture(scope="session", autouse=True)
def marketplaces_vm_push(monkeysession: pytest.MonkeyPatch) -> None:
    """Set a single-thread for VMDelete."""
    monkeysession.setattr(VMDelete, '_REQUEST_THREADS', 1)


@pytest.fixture
def ami_release() -> AmiRelease:
    params = {
        "product": "sample_product",
        "base_product": "base_product",
        "date": "2023-01-30",
        "arch": "x86_64",
        "respin": 0,
        "version": "1.0.1",
        "base_version": "1.1.1",
        "type": "GA",
    }
    return AmiRelease(**params)


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
def security_group() -> AmiSecurityGroup:
    params = {
        "from_port": 22,
        "ip_protocol": "tcp",
        "ip_ranges": ["22.22.22.22", "33.33.33.33"],
        "to_port": 22,
    }
    return AmiSecurityGroup._from_data(params)


@pytest.fixture
def access_endpoint_url() -> AmiAccessEndpointUrl:
    params = {
        "port": 22,
        "protocol": "tcp",
    }
    return AmiAccessEndpointUrl._from_data(params)


@pytest.fixture
def aws_push_item(
    ami_release: AmiRelease,
    security_group: AmiSecurityGroup,
) -> AmiPushItem:
    params = {
        "name": "sample_product-1.0.1-1-x86_64.raw",
        "description": "foo",
        "src": "/foo/bar/image.raw",
        "image_id": "ami-aws1",
        "dest": ["product-uuid"],
        "build": "sample_product-1.0.1-1-x86_64",
        "build_info": KojiBuildInfo(
            name="test-build", version="1.0.1", release="20230101", id=1234
        ),
        "virtualization": "virt",
        "volume": "gp2",
        "release": ami_release,
        "scanning_port": 22,
        "user_name": "fake-user",
        "release_notes": "https://access.redhat.com/{major_version}/{major_minor}",
        "usage_instructions": "Example. {major_version} - {major_minor}",
        "recommended_instance_type": "m5.large",
        "marketplace_entity_type": "AmiProduct",
        "security_groups": [security_group],
    }
    return AmiPushItem(**params)


@pytest.fixture
def aws_push_item_2(
    ami_release: AmiRelease,
    security_group: AmiSecurityGroup,
) -> AmiPushItem:
    params = {
        "name": "sample_product-1.0.1-1-x86_64.raw",
        "description": "foo",
        "src": "/foo/bar/image.raw",
        "image_id": "ami-aws2",
        "dest": ["product-uuid"],
        "build": "sample_product-1.0.1-1-x86_64",
        "build_info": KojiBuildInfo(
            name="test-build", version="1.0.1", release="20230101", id=1234
        ),
        "virtualization": "virt",
        "volume": "gp2",
        "release": ami_release,
        "scanning_port": 22,
        "user_name": "fake-user",
        "release_notes": "https://access.redhat.com/{major_version}/{major_minor}",
        "usage_instructions": "Example. {major_version} - {major_minor}",
        "recommended_instance_type": "m5.large",
        "marketplace_entity_type": "AmiProduct",
        "security_groups": [security_group],
    }
    return AmiPushItem(**params)


@pytest.fixture
def aws_rhcos_push_item(ami_release: AmiRelease, security_group: AmiSecurityGroup) -> AmiPushItem:
    params = {
        "name": "rhcos",
        "description": "foo",
        "src": "ami-01",
        "image_id": "ami-rhcos1",
        "dest": ["product-uuid"],
        "build": "rhcos-x86_64-414.92.202405201754-0",
        "build_info": KojiBuildInfo(
            name="test-build", version="1.0.1", release="20230101", id=1234
        ),
        "virtualization": "virt",
        "volume": "gp2",
        "type": "hourly",
        "release": ami_release,
        "scanning_port": 22,
        "release_notes": "https://access.redhat.com/{major_minor}/{major_version}-{minor_version}.html",  # noqa: E501
        "usage_instructions": "Example. {major_minor}",
        "recommended_instance_type": "m5.large",
        "marketplace_entity_type": "ACN",
        "security_groups": [security_group],
    }
    return AmiPushItem(**params)


@pytest.fixture
def vhd_push_item(release_params: Dict[str, Any], push_item_params: Dict[str, Any]) -> VHDPushItem:
    """Return a minimal VHDPushItem."""
    release = VMIRelease(**release_params)
    push_item_params.update(
        {
            "name": "azure-testing.vhd.xz",
            "release": release,
            "src": "mnt/azure/azure-testing.vhd.xz",
            "dest": ["azure-testing"],
            "build": "azure-testing",
        }
    )
    return VHDPushItem(**push_item_params)


@pytest.fixture
def pub_response_ami(
    aws_rhcos_push_item: AmiPushItem, aws_push_item: AmiPushItem
) -> List[AmiPushItem]:
    return [aws_rhcos_push_item, aws_push_item]


@pytest.fixture
def pub_response_azure(vhd_push_item: VHDPushItem) -> List[VHDPushItem]:
    return [vhd_push_item]


@pytest.fixture
def pub_response_diff_amis(
    aws_push_item_2: AmiPushItem, aws_push_item: AmiPushItem
) -> List[AmiPushItem]:
    return [aws_push_item, aws_push_item_2]


class BadPubResponse:
    name: str
    description: str
    src: str

    def __init__(self, name, description, src):
        self.name = name
        self.description = description
        self.src = src


@pytest.fixture
def bad_pub_response_vmi() -> List[BadPubResponse]:
    params = {
        "name": "vhd_pushitem",
        "description": "fakevhd",
        "src": "fake-src",
    }
    return [BadPubResponse(**params), BadPubResponse(**params)]
