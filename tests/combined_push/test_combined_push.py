# SPDX-License-Identifier: GPL-3.0-or-later
import re
import time
from typing import Type, Union
from unittest import mock

import pytest
from pushsource import AmiPushItem
from starmap_client.models import QueryResponse

from pubtools._marketplacesvm.cloud_providers import CloudProvider
from pubtools._marketplacesvm.tasks.combined_push import entry_point
from pubtools._marketplacesvm.tasks.combined_push.command import (
    CombinedVMPush,
    CommunityVMPush,
    MarketplacesVMPush,
)

from ..command import CommandTester


class UploadResponse(dict):
    """Represent a fake S3 upload response."""

    def __init__(self, *args, **kwargs):
        super(UploadResponse, self).__init__(*args, **kwargs)
        self.__dict__ = self


class FakeCloudProvider(CloudProvider):
    """Define a fake cloud provider for testing."""

    @classmethod
    def from_credentials(cls, _):
        return cls()

    def _upload(self, push_item, custom_tags=None, **kwargs):
        time.sleep(2)
        return push_item, UploadResponse({"id": "foo", "name": "bar"})

    def _pre_publish(self, push_item, **kwargs):
        return push_item, kwargs

    def _publish(self, push_item, nochannel, overwrite, preview_only, **kwargs):
        return push_item, nochannel


@pytest.fixture(autouse=True)
def fake_rhsm_api(requests_mocker):
    requests_mocker.register_uri(
        "GET",
        re.compile("amazon/provider_image_groups"),
        json={
            "body": [
                {"name": "sample_product_HOURLY", "providerShortName": "awstest"},
                {"name": "sample_product", "providerShortName": "awstest"},
                {"name": "RHEL_HA", "providerShortName": "awstest"},
                {"name": "SAP", "providerShortName": "awstest"},
            ]
        },
    )
    requests_mocker.register_uri("POST", re.compile("amazon/region"))
    requests_mocker.register_uri("PUT", re.compile("amazon/amis"))
    requests_mocker.register_uri("POST", re.compile("amazon/amis"))


@pytest.fixture(autouse=True)
def patch_push_objects(
    starmap_query_aws_marketplace: QueryResponse,
    starmap_query_aws_community: QueryResponse,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_cloud_instance = mock.MagicMock()
    mock_cloud_instance.return_value = FakeCloudProvider()
    monkeypatch.setattr(MarketplacesVMPush, 'cloud_instance', mock_cloud_instance)
    mock_starmap = mock.MagicMock()
    mock_starmap.query_image_by_name.side_effect = [
        starmap_query_aws_marketplace,
        starmap_query_aws_community,
    ]
    monkeypatch.setattr(MarketplacesVMPush, 'starmap', mock_starmap)
    monkeypatch.setattr(CommunityVMPush, 'starmap', mock_starmap)


@mock.patch("pubtools._marketplacesvm.tasks.community_push.command.Source")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
def test_do_combined_push(
    marketplace_source: mock.MagicMock,
    community_source: mock.MagicMock,
    ami_push_item: AmiPushItem,
    command_tester: CommandTester,
) -> None:
    """Test a successfull combined push for marketplaces and community workflows."""
    marketplace_source.get.return_value.__enter__.return_value = [ami_push_item]
    community_source.get.return_value.__enter__.return_value = [ami_push_item]

    command_tester.test(
        lambda: entry_point(CombinedVMPush),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--rhsm-url",
            "https://rhsm.com/test/api/",
            "--debug",
            "koji:https://fakekoji.com?vmi_build=ami_build",
        ],
    )


@pytest.mark.parametrize("fails_on", [CommunityVMPush, MarketplacesVMPush])
@mock.patch("pubtools._marketplacesvm.tasks.community_push.command.Source")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
def test_do_combined_push_fail_one_workflow(
    marketplace_source: mock.MagicMock,
    community_source: mock.MagicMock,
    fails_on: Union[Type[CommunityVMPush], Type[MarketplacesVMPush]],
    ami_push_item: AmiPushItem,
    monkeypatch: pytest.MonkeyPatch,
    command_tester: CommandTester,
) -> None:
    """Test a combined push which succeds in one workflow and fails in another one."""

    class BadFakeCloudProvider(FakeCloudProvider):

        def _upload(self, push_item, custom_tags=None, **kwargs):
            raise RuntimeError("Testing error")

    marketplace_source.get.return_value.__enter__.return_value = [ami_push_item]
    community_source.get.return_value.__enter__.return_value = [ami_push_item]

    mock_bad_cloud_instance = mock.MagicMock()
    mock_good_cloud_instance = mock.MagicMock()
    mock_bad_cloud_instance.return_value = BadFakeCloudProvider()
    mock_good_cloud_instance.return_value = FakeCloudProvider()
    if fails_on == CommunityVMPush:
        succeeds_on = MarketplacesVMPush
    else:
        succeeds_on = CommunityVMPush
    monkeypatch.setattr(fails_on, 'cloud_instance', mock_bad_cloud_instance)
    monkeypatch.setattr(succeeds_on, 'cloud_instance', mock_good_cloud_instance)

    command_tester.test(
        lambda: entry_point(CombinedVMPush),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--rhsm-url",
            "https://rhsm.com/test/api/",
            "--debug",
            "koji:https://fakekoji.com?vmi_build=ami_build",
        ],
    )


@mock.patch("pubtools._marketplacesvm.tasks.community_push.command.Source")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
def test_do_combined_push_both_skipped(
    marketplace_source: mock.MagicMock,
    community_source: mock.MagicMock,
    command_tester: CommandTester,
) -> None:
    """Test a combined push which fails as both workflows are empty."""
    marketplace_source.get.return_value.__enter__.return_value = []
    community_source.get.return_value.__enter__.return_value = []

    command_tester.test(
        lambda: entry_point(CombinedVMPush),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--rhsm-url",
            "https://rhsm.com/test/api/",
            "--debug",
            "koji:https://fakekoji.com?vmi_build=ami_build",
        ],
    )


@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
@mock.patch("pubtools._marketplacesvm.tasks.community_push.command.Source")
def test_do_community_push(
    community_source: mock.MagicMock,
    marketplace_source: mock.MagicMock,
    ami_push_item: AmiPushItem,
    starmap_query_aws_community: QueryResponse,
    monkeypatch: pytest.MonkeyPatch,
    command_tester: CommandTester,
) -> None:
    """Test a successfull community push using the CombinedVMPush."""
    community_source.get.return_value.__enter__.return_value = [ami_push_item]

    mock_starmap = mock.MagicMock()
    mock_starmap.query_image_by_name.side_effect = [
        starmap_query_aws_community,
    ]
    monkeypatch.setattr(CommunityVMPush, 'starmap', mock_starmap)

    command_tester.test(
        lambda: entry_point(CombinedVMPush),
        [
            "test-push",
            "--workflow",
            "community",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--rhsm-url",
            "https://rhsm.com/test/api/",
            "--debug",
            "koji:https://fakekoji.com?vmi_build=ami_build",
        ],
    )
    marketplace_source.get.assert_not_called()


@mock.patch("pubtools._marketplacesvm.tasks.community_push.command.Source")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
def test_do_marketplace_push(
    marketplace_source: mock.MagicMock,
    community_source: mock.MagicMock,
    ami_push_item: AmiPushItem,
    starmap_query_aws_marketplace: QueryResponse,
    monkeypatch: pytest.MonkeyPatch,
    command_tester: CommandTester,
) -> None:
    """Test a successfull marketplace push using the CombinedVMPush."""
    marketplace_source.get.return_value.__enter__.return_value = [ami_push_item]

    mock_starmap = mock.MagicMock()
    mock_starmap.query_image_by_name.side_effect = [
        starmap_query_aws_marketplace,
    ]
    monkeypatch.setattr(MarketplacesVMPush, 'starmap', mock_starmap)

    command_tester.test(
        lambda: entry_point(CombinedVMPush),
        [
            "test-push",
            "--workflow",
            "marketplace",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--rhsm-url",
            "https://rhsm.com/test/api/",
            "--debug",
            "koji:https://fakekoji.com?vmi_build=ami_build",
        ],
    )
    community_source.get.assert_not_called()
