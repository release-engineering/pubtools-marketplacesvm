# SPDX-License-Identifier: GPL-3.0-or-later
import logging
from datetime import datetime
from typing import Any, Dict, Generator, List
from unittest import mock

import pytest
from attrs import evolve
from pushsource import AmiPushItem, AmiRelease, KojiBuildInfo
from starmap_client.models import QueryResponseContainer, QueryResponseEntity

from pubtools._marketplacesvm.cloud_providers.base import CloudProvider
from pubtools._marketplacesvm.tasks.push import MarketplacesVMPush, entry_point
from pubtools._marketplacesvm.tasks.push.items import State

from ..command import CommandTester


class FakeCloudProvider(CloudProvider):
    """Define a fake cloud provider for testing."""

    @classmethod
    def from_credentials(cls, _):
        return cls()

    def _upload(self, push_item, custom_tags=None, **kwargs):
        return push_item, True

    def _pre_publish(self, push_item, **kwargs):
        return push_item, kwargs

    def _publish(self, push_item, nochannel, overwrite, **kwargs):
        return push_item, nochannel

    def _delete_push_images(self, push_item, **kwargs):
        return push_item


@pytest.fixture()
def fake_cloud_instance() -> Generator[mock.MagicMock, None, None]:
    with mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.cloud_instance") as m:
        m.return_value = FakeCloudProvider()
        yield m


@pytest.fixture
def push_item_params() -> Dict[str, Any]:
    return {
        "name": "name",
        "description": "",
        "build_info": KojiBuildInfo(name="sample-product", version="7.0", release="1"),
    }


@pytest.fixture
def ami_multi_arch_push_items(
    release_params: Dict[str, Any], push_item_params: Dict[str, Any]
) -> List[AmiPushItem]:
    """Return a minimal AmiPushItem."""
    release_x86_64 = AmiRelease(**release_params)
    release_params.update(arch="aarch64")
    release_aarch64 = AmiRelease(**release_params)

    push_item_x86_64_params = push_item_params.copy()
    push_item_x86_64_params.update(
        {
            "name": "sample-product-7.0-1.x86_64.raw.xz",
            "release": release_x86_64,
            "dest": ["starmap"],
        }
    )
    ami_x86_64_pi = AmiPushItem(**push_item_x86_64_params)

    push_item_aarch64_params = push_item_params.copy()
    push_item_aarch64_params.update(
        {
            "name": "sample-product-7.0-1.aarch64.raw.xz",
            "release": release_aarch64,
            "dest": ["starmap"],
        }
    )
    ami_aarch64_pi = AmiPushItem(**push_item_aarch64_params)

    return [ami_x86_64_pi, ami_aarch64_pi]


AMI_NA_X86_64_ID = "fake-ami-id-for-na-x86-64"
AMI_EMEA_X86_64_ID = "fake-ami-id-for-emea-x86-64"
AMI_NA_AARCH64_ID = "fake-ami-id-for-na-aarch64"
AMI_EMEA_AARCH64_ID = "fake-ami-id-for-emea-aarch64"


class FakeAWSProvider(FakeCloudProvider):
    amis: List[str] = []
    log = logging.getLogger("pubtools.marketplacesvm")

    def _upload(self, push_item, custom_tags=None, **kwargs):
        push_item = evolve(push_item, image_id=self.amis.pop(0))
        return push_item, True

    def _pre_publish(self, push_item, **kwargs):
        return push_item, kwargs

    def _publish(self, push_item, nochannel, overwrite, **kwargs):
        # This log will allow us to identify whether the image_id is the expected
        self.log.debug(f"Pushing {push_item.name} with image: {push_item.image_id}")
        return push_item, nochannel


@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.cloud_instance")
@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.starmap")
def test_do_push_x86_64_starmap_filter(
    mock_starmap: mock.MagicMock,
    mock_source: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
    mock_cloud_instance: mock.MagicMock,
    ami_multi_arch_push_items: List[AmiPushItem],
    command_tester: CommandTester,
) -> None:
    """Test a successful push for AWS multi-arch koji build with aarch64 filtered out.

    There should be expected x86_64 AMI ID, and recommended_instance_type.
    Each push item should have expected description based on marketplace
    All aarch64 images are filtered out based on starmap mappings.
    """
    provider = FakeAWSProvider()
    provider.amis = [AMI_NA_X86_64_ID, AMI_EMEA_X86_64_ID]
    mock_cloud_instance.return_value = provider

    qre = QueryResponseEntity.from_json(
        {
            "name": "fake-policy",
            "workflow": "stratosphere",
            "cloud": "aws",
            "mappings": {
                "aws-na": {
                    "destinations": [
                        {
                            "destination": "NA-DESTINATION",
                            "architecture": "x86_64",
                            "overwrite": False,
                            "restrict_version": True,
                            "restrict_major": 3,
                            "restrict_minor": 1,
                            "meta": {"recommended_instance_type": "m5.large"},
                        },
                    ],
                    "meta": {"description": "NA description"},
                },
                "aws-emea": {
                    "destinations": [
                        {
                            "destination": "EMEA-DESTINATION",
                            "architecture": "x86_64",
                            "overwrite": False,
                            "restrict_version": True,
                            "restrict_major": 3,
                            "restrict_minor": 1,
                            "meta": {"recommended_instance_type": "m5.large"},
                        },
                    ],
                    "meta": {"description": "EMEA description"},
                },
            },
        }
    )
    mock_starmap.query_image_by_name.return_value = QueryResponseContainer([qre])
    mock_source.get.return_value.__enter__.return_value = ami_multi_arch_push_items

    command_tester.test(
        lambda: entry_point(MarketplacesVMPush),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--debug",
            "koji:https://fakekoji.com?vmi_build=sample-product-7.0-1",
        ],
    )

    mock_source.get.assert_called_once()
    mock_starmap.query_image_by_name.assert_called_with(name="sample-product", version="7.0")
    mock_starmap.query_image_by_name.assert_called_with(name="sample-product", version="7.0")
    assert mock_starmap.query_image_by_name.call_count == 2
    assert mock_cloud_instance.call_count == 6

    exp_ami_release = AmiRelease(
        product="sample-product",
        date=datetime(2025, 4, 2, 17, 56, 59),
        arch="x86_64",
        respin=1,
        version="7.0",
    )

    exp_na_pi = AmiPushItem(
        **dict(
            name="sample-product-7.0-1.x86_64.raw.xz",
            state=State.PUSHED,
            build_info=KojiBuildInfo(name="sample-product", version="7.0", release="1"),
            release=exp_ami_release,
            dest=["NA-DESTINATION"],
            description="NA description",
            recommended_instance_type="m5.large",
            image_id="fake-ami-id-for-na-x86-64",
        )
    )
    exp_emea_pi = AmiPushItem(
        **dict(
            name="sample-product-7.0-1.x86_64.raw.xz",
            state=State.PUSHED,
            build_info=KojiBuildInfo(name="sample-product", version="7.0", release="1"),
            release=exp_ami_release,
            dest=["EMEA-DESTINATION"],
            description="EMEA description",
            recommended_instance_type="m5.large",
            image_id="fake-ami-id-for-emea-x86-64",
        )
    )

    mock_collector_update_push_items.assert_called_once()
    # aarch64 builds are missing
    assert mock_collector_update_push_items.call_args[0][0] == [exp_na_pi, exp_emea_pi]


@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.cloud_instance")
@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.starmap")
def test_do_push_aarch64_starmap_filter(
    mock_starmap: mock.MagicMock,
    mock_source: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
    mock_cloud_instance: mock.MagicMock,
    ami_multi_arch_push_items: List[AmiPushItem],
    command_tester: CommandTester,
) -> None:
    """Test a successful push for AWS multi-arch koji build with x86_64 filtered out.

    There should be expected aarch64 AMI ID, and recommended_instance_type.
    Each push item should have expected description based on marketplace
    All x86_64 images are filtered out based on starmap mappings.
    """
    provider = FakeAWSProvider()
    provider.amis = [AMI_NA_AARCH64_ID, AMI_EMEA_AARCH64_ID]
    mock_cloud_instance.return_value = provider

    qre = QueryResponseEntity.from_json(
        {
            "name": "fake-policy",
            "workflow": "stratosphere",
            "cloud": "aws",
            "mappings": {
                "aws-na": {
                    "destinations": [
                        {
                            "destination": "NA-DESTINATION",
                            "architecture": "aarch64",
                            "overwrite": False,
                            "restrict_version": True,
                            "restrict_major": 3,
                            "restrict_minor": 1,
                            "meta": {"recommended_instance_type": "m6g.large"},
                        },
                    ],
                    "meta": {"description": "NA description"},
                },
                "aws-emea": {
                    "destinations": [
                        {
                            "destination": "EMEA-DESTINATION",
                            "architecture": "aarch64",
                            "overwrite": False,
                            "restrict_version": True,
                            "restrict_major": 3,
                            "restrict_minor": 1,
                            "meta": {"recommended_instance_type": "m6g.large"},
                        },
                    ],
                    "meta": {"description": "EMEA description"},
                },
            },
        }
    )
    mock_starmap.query_image_by_name.return_value = QueryResponseContainer([qre])
    mock_source.get.return_value.__enter__.return_value = ami_multi_arch_push_items

    command_tester.test(
        lambda: entry_point(MarketplacesVMPush),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--debug",
            "koji:https://fakekoji.com?vmi_build=sample-product-7.0-1",
        ],
    )

    mock_source.get.assert_called_once()
    mock_starmap.query_image_by_name.assert_called_with(name="sample-product", version="7.0")
    mock_starmap.query_image_by_name.assert_called_with(name="sample-product", version="7.0")
    assert mock_starmap.query_image_by_name.call_count == 2
    assert mock_cloud_instance.call_count == 6

    exp_ami_release = AmiRelease(
        product="sample-product",
        date=datetime(2025, 4, 2, 17, 56, 59),
        arch="aarch64",
        respin=1,
        version="7.0",
    )

    exp_na_pi = AmiPushItem(
        **dict(
            name="sample-product-7.0-1.aarch64.raw.xz",
            state=State.PUSHED,
            build_info=KojiBuildInfo(name="sample-product", version="7.0", release="1"),
            release=exp_ami_release,
            dest=["NA-DESTINATION"],
            description="NA description",
            recommended_instance_type="m6g.large",
            image_id="fake-ami-id-for-na-aarch64",
        )
    )
    exp_emea_pi = AmiPushItem(
        **dict(
            name="sample-product-7.0-1.aarch64.raw.xz",
            state=State.PUSHED,
            build_info=KojiBuildInfo(name="sample-product", version="7.0", release="1"),
            release=exp_ami_release,
            dest=["EMEA-DESTINATION"],
            description="EMEA description",
            recommended_instance_type="m6g.large",
            image_id="fake-ami-id-for-emea-aarch64",
        )
    )

    mock_collector_update_push_items.assert_called_once()
    # x86_64 builds are missing
    assert mock_collector_update_push_items.call_args[0][0] == [exp_na_pi, exp_emea_pi]


@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.cloud_instance")
@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.starmap")
def test_do_push_all_architectures_different_destination(
    mock_starmap: mock.MagicMock,
    mock_source: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
    mock_cloud_instance: mock.MagicMock,
    ami_multi_arch_push_items: List[AmiPushItem],
    command_tester: CommandTester,
) -> None:
    """Test a successful push for AWS multi-arch koji build.

    Each image will be delivered to the different destination
    All x86_64 images will have recommended instance type m5.large.
    All aarch64 images will have recommended instance type m6g.large
    All images for aws-na will have description NA description
    All images for aws-emea will have EMEA description
    """
    provider = FakeAWSProvider()
    provider.amis = [AMI_NA_X86_64_ID, AMI_EMEA_X86_64_ID, AMI_NA_AARCH64_ID, AMI_EMEA_AARCH64_ID]
    mock_cloud_instance.return_value = provider
    qre = QueryResponseEntity.from_json(
        {
            "name": "fake-policy",
            "workflow": "stratosphere",
            "cloud": "aws",
            "mappings": {
                "aws-na": {
                    "destinations": [
                        {
                            "destination": "NA-DESTINATION-X86_64-PRODUCT-ID",
                            "architecture": "x86_64",
                            "overwrite": False,
                            "restrict_version": True,
                            "restrict_major": 3,
                            "restrict_minor": 1,
                            "meta": {"recommended_instance_type": "m5.large"},
                        },
                        {
                            "destination": "NA-DESTINATION-AARCH64-PRODUCT-ID",
                            "architecture": "aarch64",
                            "overwrite": False,
                            "restrict_version": True,
                            "restrict_major": 3,
                            "restrict_minor": 1,
                            "meta": {"recommended_instance_type": "m6g.large"},
                        },
                    ],
                    "meta": {"description": "NA description"},
                },
                "aws-emea": {
                    "destinations": [
                        {
                            "destination": "EMEA-DESTINATION-X86_64-PRODUCT-ID",
                            "architecture": "x86_64",
                            "overwrite": False,
                            "restrict_version": True,
                            "restrict_major": 3,
                            "restrict_minor": 1,
                            "meta": {"recommended_instance_type": "m5.large"},
                        },
                        {
                            "destination": "EMEA-DESTINATION-AARCH64-PRODUCT-ID",
                            "architecture": "aarch64",
                            "overwrite": False,
                            "restrict_version": True,
                            "restrict_major": 3,
                            "restrict_minor": 1,
                            "meta": {"recommended_instance_type": "m6g.large"},
                        },
                    ],
                    "meta": {"description": "EMEA description"},
                },
            },
        }
    )
    mock_starmap.query_image_by_name.return_value = QueryResponseContainer([qre])
    mock_source.get.return_value.__enter__.return_value = ami_multi_arch_push_items

    command_tester.test(
        lambda: entry_point(MarketplacesVMPush),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--debug",
            "koji:https://fakekoji.com?vmi_build=sample-product-7.0-1",
        ],
    )

    mock_source.get.assert_called_once()
    mock_starmap.query_image_by_name.assert_called_with(name="sample-product", version="7.0")
    mock_starmap.query_image_by_name.assert_called_with(name="sample-product", version="7.0")
    assert mock_starmap.query_image_by_name.call_count == 2
    assert mock_cloud_instance.call_count == 12

    shared_ami_release_data = {
        "product": "sample-product",
        "date": datetime(2025, 4, 2, 17, 56, 59),
        "respin": 1,
        "version": "7.0",
    }

    exp_ami_x86_64_release = AmiRelease(arch="x86_64", **shared_ami_release_data)
    exp_ami_aarch64_release = AmiRelease(arch="aarch64", **shared_ami_release_data)

    exp_na_x86_64_pi = AmiPushItem(
        **dict(
            name="sample-product-7.0-1.x86_64.raw.xz",
            state=State.PUSHED,
            build_info=KojiBuildInfo(name="sample-product", version="7.0", release="1"),
            release=exp_ami_x86_64_release,
            dest=["NA-DESTINATION-X86_64-PRODUCT-ID"],
            description="NA description",
            recommended_instance_type="m5.large",
            image_id="fake-ami-id-for-na-x86-64",
        )
    )

    exp_emea_x86_64_pi = AmiPushItem(
        **dict(
            name="sample-product-7.0-1.x86_64.raw.xz",
            state=State.PUSHED,
            build_info=KojiBuildInfo(name="sample-product", version="7.0", release="1"),
            release=exp_ami_x86_64_release,
            dest=["EMEA-DESTINATION-X86_64-PRODUCT-ID"],
            description="EMEA description",
            recommended_instance_type="m5.large",
            image_id="fake-ami-id-for-emea-x86-64",
        )
    )

    exp_na_aarch64_pi = AmiPushItem(
        **dict(
            name="sample-product-7.0-1.aarch64.raw.xz",
            state=State.PUSHED,
            build_info=KojiBuildInfo(name="sample-product", version="7.0", release="1"),
            release=exp_ami_aarch64_release,
            dest=["NA-DESTINATION-AARCH64-PRODUCT-ID"],
            description="NA description",
            recommended_instance_type="m6g.large",
            image_id="fake-ami-id-for-na-aarch64",
        )
    )

    exp_emea_aarch64_pi = AmiPushItem(
        **dict(
            name="sample-product-7.0-1.aarch64.raw.xz",
            state=State.PUSHED,
            build_info=KojiBuildInfo(name="sample-product", version="7.0", release="1"),
            release=exp_ami_aarch64_release,
            dest=["EMEA-DESTINATION-AARCH64-PRODUCT-ID"],
            description="EMEA description",
            recommended_instance_type="m6g.large",
            image_id="fake-ami-id-for-emea-aarch64",
        )
    )

    mock_collector_update_push_items.assert_called_once()
    # each push item has unique combination of destination, description
    # and recommended_instance_type
    assert mock_collector_update_push_items.call_args[0][0] == [
        exp_na_x86_64_pi,
        exp_emea_x86_64_pi,
        exp_na_aarch64_pi,
        exp_emea_aarch64_pi,
    ]
