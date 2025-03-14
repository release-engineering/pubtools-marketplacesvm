# SPDX-License-Identifier: GPL-3.0-or-later
import json
import re
from copy import deepcopy
from typing import Any, Dict, Type, Union
from unittest import mock

import pytest
from attrs import asdict, evolve
from pushsource import AmiPushItem, AmiRelease, KojiBuildInfo
from starmap_client import StarmapClient
from starmap_client.models import QueryResponseContainer
from starmap_client.providers import InMemoryMapProviderV2

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
        return push_item, UploadResponse({"id": "foo", "name": "bar"})

    def _pre_publish(self, push_item, **kwargs):
        return push_item, kwargs

    def _publish(self, push_item, nochannel, overwrite, **kwargs):
        return push_item, nochannel

    def _delete_push_images(self, push_item, **kwargs):
        return push_item


@pytest.fixture(autouse=True)
def reset_borg():
    obj = CombinedVMPush()
    obj.builds_borg.received_builds.clear()
    obj.builds_borg.processed_builds.clear()


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
    starmap_query_aws_marketplace: QueryResponseContainer,
    starmap_query_aws_community: QueryResponseContainer,
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


def _check_collector_update_push_items(
    mock_collector_update_push_items: mock.MagicMock,
    expected_ami_pi_count: int,
) -> None:
    assert mock_collector_update_push_items.call_count == 1
    collected_push_items = mock_collector_update_push_items.call_args[0][0]
    assert len(collected_push_items) == expected_ami_pi_count


@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.community_push.command.Source")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
def test_do_combined_push(
    marketplace_source: mock.MagicMock,
    community_source: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
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

    _check_collector_update_push_items(mock_collector_update_push_items, expected_ami_pi_count=10)


@pytest.mark.parametrize("fails_on", [CommunityVMPush, MarketplacesVMPush])
@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.community_push.command.Source")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
def test_do_combined_push_fail_one_workflow(
    marketplace_source: mock.MagicMock,
    community_source: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
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

    _check_collector_update_push_items(mock_collector_update_push_items, expected_ami_pi_count=10)


@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.community_push.command.Source")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
def test_do_combined_push_both_skipped(
    marketplace_source: mock.MagicMock,
    community_source: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
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

    _check_collector_update_push_items(mock_collector_update_push_items, expected_ami_pi_count=0)


@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
@mock.patch("pubtools._marketplacesvm.tasks.community_push.command.Source")
def test_do_community_push(
    community_source: mock.MagicMock,
    marketplace_source: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
    ami_push_item: AmiPushItem,
    starmap_query_aws_community: QueryResponseContainer,
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

    _check_collector_update_push_items(mock_collector_update_push_items, expected_ami_pi_count=8)


@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.community_push.command.Source")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
def test_do_marketplace_push(
    marketplace_source: mock.MagicMock,
    community_source: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
    ami_push_item: AmiPushItem,
    starmap_query_aws_marketplace: QueryResponseContainer,
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

    _check_collector_update_push_items(mock_collector_update_push_items, expected_ami_pi_count=2)


@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.community_push.command.Source")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
def test_do_advisory_push(
    marketplace_source: mock.MagicMock,
    community_source: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
    ami_push_item: AmiPushItem,
    release_params: Dict[str, Any],
    starmap_query_aws_marketplace: QueryResponseContainer,
    starmap_query_aws_community: QueryResponseContainer,
    monkeypatch: pytest.MonkeyPatch,
    command_tester: CommandTester,
) -> None:
    """Test two builds which one contains mappings for both workflows and the other doesn't."""
    # Set starmap to only provide mappings for the first push item
    mock_starmap = mock.MagicMock()
    mock_starmap.query_image_by_name.side_effect = [
        starmap_query_aws_marketplace,
        None,
        starmap_query_aws_community,
        None,
    ]
    monkeypatch.setattr(CommunityVMPush, 'starmap', mock_starmap)
    monkeypatch.setattr(MarketplacesVMPush, 'starmap', mock_starmap)

    # Setup a second push item which will not have mappings
    second_release = deepcopy(release_params)
    second_release["product"] = "second_product"  # different name with no mappings
    second_release["date"] = "2024-01-01"
    second_binfo = KojiBuildInfo(id=2, name="second-build", version="8.0", release="11111111")
    second_build = deepcopy(ami_push_item)
    second_build = evolve(
        second_build,
        name="second_push_item",
        build_info=second_binfo,
        release=AmiRelease(**second_release),
    )

    # Add push items in the queue
    marketplace_source.get.return_value.__enter__.return_value = [ami_push_item, second_build]
    community_source.get.return_value.__enter__.return_value = [ami_push_item, second_build]

    # Test
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
            "koji:https://fakekoji.com?vmi_build=ami_build,ami_build2",
        ],
    )

    _check_collector_update_push_items(mock_collector_update_push_items, expected_ami_pi_count=10)


@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.community_push.command.Source")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
def test_do_allowed_empty_mapping_push(
    marketplace_source: mock.MagicMock,
    community_source: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
    ami_push_item: AmiPushItem,
    release_params: Dict[str, Any],
    starmap_query_aws_marketplace: QueryResponseContainer,
    starmap_query_aws_community: QueryResponseContainer,
    monkeypatch: pytest.MonkeyPatch,
    command_tester: CommandTester,
) -> None:
    """Ensure 2 push items with same build ID will not be marked as failed when second skips."""
    # Set starmap to only provide mappings for the first push item
    mock_starmap = mock.MagicMock()
    mock_starmap.query_image_by_name.side_effect = [
        starmap_query_aws_marketplace,
        None,
        starmap_query_aws_community,
        None,
    ]
    monkeypatch.setattr(CommunityVMPush, 'starmap', mock_starmap)
    monkeypatch.setattr(MarketplacesVMPush, 'starmap', mock_starmap)

    # Setup a second push item which will not have mappings
    second_release = deepcopy(release_params)
    second_release["product"] = "second_product"  # different name with no mappings
    second_release["date"] = "2024-01-01"
    second_build = deepcopy(ami_push_item)
    second_build = evolve(
        second_build,
        name="second_push_item",
        release=AmiRelease(**second_release),
    )

    # Add push items in the queue
    marketplace_source.get.return_value.__enter__.return_value = [ami_push_item, second_build]
    community_source.get.return_value.__enter__.return_value = [ami_push_item, second_build]

    # Test
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
            "koji:https://fakekoji.com?vmi_build=ami_build,ami_build2",
        ],
    )

    _check_collector_update_push_items(mock_collector_update_push_items, expected_ami_pi_count=10)


@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.community_push.command.Source")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
def test_do_combined_push_overriden_destination(
    marketplace_source: mock.MagicMock,
    community_source: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
    ami_push_item: AmiPushItem,
    starmap_query_aws_marketplace: QueryResponseContainer,
    starmap_query_aws_community: QueryResponseContainer,
    command_tester: CommandTester,
    monkeypatch: pytest.MonkeyPatch,
    tmpdir: pytest.Testdir,
) -> None:
    """Test a successfull combined push for marketplaces and community workflows."""
    # Store the auto-assigned mocks for StArMap on both workflows
    mock_starmap_mkt = MarketplacesVMPush.starmap
    mock_starmap_cmt = CommunityVMPush.starmap

    # The policy name must be the same for community and marketplace workflows
    qre = starmap_query_aws_marketplace.responses.pop()
    qre = evolve(qre, name="sample_product")
    starmap_query_aws_marketplace.responses.append(qre)
    binfo = KojiBuildInfo(name="sample_product", version="7.0", release="20230101")
    ami_push_item = evolve(ami_push_item, build_info=binfo)

    # Create a testing StArMap instance which will fail to resolve the server
    # it is, it can only be used offline
    responses = starmap_query_aws_community.responses + starmap_query_aws_marketplace.responses
    provider = InMemoryMapProviderV2(QueryResponseContainer(responses))
    starmap = StarmapClient("https://foo.com/bar", provider=provider)
    monkeypatch.setattr(MarketplacesVMPush, 'starmap', starmap)
    monkeypatch.setattr(CommunityVMPush, 'starmap', starmap)

    # Add the push items in the queue
    marketplace_source.get.return_value.__enter__.return_value = [ami_push_item]
    community_source.get.return_value.__enter__.return_value = [ami_push_item]

    # Test
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
            "--repo",
            json.dumps([asdict(x) for x in responses], default=str),
            "--debug",
            "koji:https://fakekoji.com?vmi_build=ami_build",
        ],
    )

    # Ensure the "server" was not called
    mock_starmap_mkt.query_image_by_name.assert_not_called()
    mock_starmap_cmt.query_image_by_name.assert_not_called()

    _check_collector_update_push_items(mock_collector_update_push_items, expected_ami_pi_count=10)
