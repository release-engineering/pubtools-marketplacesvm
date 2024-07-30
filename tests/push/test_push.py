# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import time
from typing import Generator
from unittest import mock

import pytest
from _pytest.capture import CaptureFixture
from attrs import evolve
from pushsource import AmiPushItem, PushItem, VHDPushItem
from starmap_client.models import QueryResponse

from pubtools._marketplacesvm.cloud_providers.base import CloudProvider
from pubtools._marketplacesvm.tasks.push import MarketplacesVMPush, entry_point

from ..command import CommandTester


class FakeCloudProvider(CloudProvider):
    """Define a fake cloud provider for testing."""

    @classmethod
    def from_credentials(cls, _):
        return cls()

    def _upload(self, push_item, custom_tags=None, **kwargs):
        time.sleep(2)
        return push_item, True

    def _pre_publish(self, push_item, **kwargs):
        return push_item, kwargs

    def _publish(self, push_item, nochannel, overwrite, **kwargs):
        return push_item, nochannel


@pytest.fixture()
def fake_source(
    ami_push_item: AmiPushItem, vhd_push_item: VHDPushItem
) -> Generator[mock.MagicMock, None, None]:
    with mock.patch("pubtools._marketplacesvm.tasks.push.command.Source") as m:
        m.get.return_value.__enter__.return_value = [ami_push_item, vhd_push_item]
        yield m


@pytest.fixture()
def fake_starmap(
    starmap_query_aws: QueryResponse, starmap_query_azure: QueryResponse
) -> Generator[mock.MagicMock, None, None]:
    with mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.starmap") as m:
        m.query_image_by_name.side_effect = [starmap_query_aws, starmap_query_azure]
        yield m


@pytest.fixture()
def fake_cloud_instance() -> Generator[mock.MagicMock, None, None]:
    with mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.cloud_instance") as m:
        m.return_value = FakeCloudProvider()
        yield m


def test_do_push(
    fake_source: mock.MagicMock,
    fake_cloud_instance: mock.MagicMock,
    fake_starmap: mock.MagicMock,
    command_tester: CommandTester,
) -> None:
    """Test a successfull push."""
    command_tester.test(
        lambda: entry_point(MarketplacesVMPush),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--debug",
            "koji:https://fakekoji.com?vmi_build=ami_build,azure_build",
        ],
    )

    fake_source.get.assert_called_once()
    starmap_calls = [mock.call(name="test-build", version="7.0") for _ in range(2)]
    fake_starmap.query_image_by_name.assert_has_calls(starmap_calls)
    # get_provider, upload, pre_publish and publish calls for "aws-na", "aws-emea", "azure-na"
    assert fake_cloud_instance.call_count == 16


@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.cloud_instance")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.starmap")
def test_do_push_ami_correct_id(
    mock_starmap: mock.MagicMock,
    mock_source: mock.MagicMock,
    mock_cloud_instance: mock.MagicMock,
    ami_push_item: AmiPushItem,
    command_tester: CommandTester,
) -> None:
    """Test a successful push for AWS using the correct AMI ID for each marketplace."""
    ami_na = "fake-ami-id-for-na"
    ami_emea = "fake-ami-id-for-emea"

    class FakeAWSProvider(FakeCloudProvider):
        amis = [ami_na, ami_emea]
        log = logging.getLogger("pubtools.marketplacesvm")

        def _upload(self, push_item, custom_tags=None, **kwargs):
            time.sleep(2)
            push_item = evolve(push_item, image_id=self.amis.pop(0))
            return push_item, True

        def _pre_publish(self, push_item, **kwargs):
            return push_item, kwargs

        def _publish(self, push_item, nochannel, overwrite, **kwargs):
            # This log will allow us to identify whether the image_id is the expected
            self.log.debug(f"Pushing {push_item.name} with image: {push_item.image_id}")
            return push_item, nochannel

    mock_cloud_instance.return_value = FakeAWSProvider()

    qr = QueryResponse.from_json(
        {
            "name": "fake-policy",
            "workflow": "stratosphere",
            "mappings": {
                "aws-na": [
                    {
                        "destination": "NA-DESTINATION",
                        "overwrite": False,
                        "restrict_version": True,
                        "restrict_major": 3,
                        "restrict_minor": 1,
                    },
                ],
                "aws-emea": [
                    {
                        "destination": "EMEA-DESTINATION",
                        "overwrite": False,
                        "restrict_version": True,
                        "restrict_major": 3,
                        "restrict_minor": 1,
                    },
                ],
            },
        }
    )
    mock_starmap.query_image_by_name.return_value = qr
    mock_source.get.return_value.__enter__.return_value = [ami_push_item]

    command_tester.test(
        lambda: entry_point(MarketplacesVMPush),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--debug",
            "koji:https://fakekoji.com?vmi_build=aws_build",
        ],
    )

    mock_source.get.assert_called_once()
    mock_starmap.query_image_by_name.assert_called_once_with(name="test-build", version="7.0")
    assert mock_cloud_instance.call_count == 8


@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.cloud_instance")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.starmap")
def test_do_push_azure_correct_sas(
    mock_starmap: mock.MagicMock,
    mock_source: mock.MagicMock,
    mock_cloud_instance: mock.MagicMock,
    vhd_push_item: VHDPushItem,
    command_tester: CommandTester,
) -> None:
    """Test a successful push for Azure using the correct SAS URI for each marketplace."""
    azure_na = "fake-azure-sas-for-na"
    azure_emea = "fake-azure-sas-for-emea"

    class FakeAzureProvider(FakeCloudProvider):
        vhds = [azure_na, azure_emea]
        log = logging.getLogger("pubtools.marketplacesvm")

        def _upload(self, push_item, custom_tags=None, **kwargs):
            time.sleep(2)
            push_item = evolve(push_item, sas_uri=self.vhds.pop(0))
            return push_item, True

        def _pre_publish(self, push_item, **kwargs):
            return push_item, kwargs

        def _publish(self, push_item, nochannel, overwrite, **kwargs):
            # This log will allow us to identify whether the sas_uri is the expected
            self.log.debug(f"Pushing {push_item.name} with image: {push_item.sas_uri}")
            return push_item, nochannel

    mock_cloud_instance.return_value = FakeAzureProvider()

    qr = QueryResponse.from_json(
        {
            "name": "fake-policy",
            "workflow": "stratosphere",
            "mappings": {
                "azure-na": [
                    {
                        "destination": "NA-DESTINATION",
                        "overwrite": False,
                        "restrict_version": False,
                    },
                ],
                "azure-emea": [
                    {
                        "destination": "EMEA-DESTINATION",
                        "overwrite": False,
                        "restrict_version": False,
                    },
                ],
            },
        }
    )
    mock_starmap.query_image_by_name.return_value = qr
    mock_source.get.return_value.__enter__.return_value = [vhd_push_item]

    command_tester.test(
        lambda: entry_point(MarketplacesVMPush),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--debug",
            "koji:https://fakekoji.com?vmi_build=azure_build",
        ],
    )

    mock_source.get.assert_called_once()
    mock_starmap.query_image_by_name.assert_called_once_with(name="test-build", version="7.0")
    assert mock_cloud_instance.call_count == 8


def test_do_push_prepush(
    fake_source: mock.MagicMock,
    fake_cloud_instance: mock.MagicMock,
    fake_starmap: mock.MagicMock,
    command_tester: CommandTester,
) -> None:
    """Test a successfull push."""
    command_tester.test(
        lambda: entry_point(MarketplacesVMPush),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--debug",
            "--pre-push",
            "koji:https://fakekoji.com?vmi_build=ami_build,azure_build",
        ],
    )

    fake_source.get.assert_called_once()
    starmap_calls = [mock.call(name="test-build", version="7.0") for _ in range(2)]
    fake_starmap.query_image_by_name.assert_has_calls(starmap_calls)
    # get_provider and upload only calls for "aws-na", "aws-emea", "azure-na"
    assert fake_cloud_instance.call_count == 3


@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
def test_not_vmi_push_item(
    mock_source: mock.MagicMock,
    fake_cloud_instance: mock.MagicMock,
    fake_starmap: mock.MagicMock,
    ami_push_item: AmiPushItem,
    command_tester: CommandTester,
) -> None:
    """Ensure non VMI pushitem is skipped from inclusion in push list."""
    mock_source.get.return_value.__enter__.return_value = [
        PushItem(name="foo", src="bar"),
        ami_push_item,
    ]

    command_tester.test(
        lambda: entry_point(MarketplacesVMPush),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--debug",
            "koji:https://fakekoji.com?vmi_build=unknown_build,ami_build",
        ],
    )

    fake_starmap.query_image_by_name.assert_called_once()
    # get_provider, upload and publish calls for "aws-na", "aws-emea"
    assert fake_cloud_instance.call_count == 8


@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
def test_push_item_wrong_arch(
    mock_source: mock.MagicMock,
    fake_cloud_instance: mock.MagicMock,
    fake_starmap: mock.MagicMock,
    ami_push_item: AmiPushItem,
    vhd_push_item: VHDPushItem,
    command_tester: CommandTester,
) -> None:
    """Ensure the push item with no mappings for a given arch is filtered out."""
    release = evolve(ami_push_item.release, arch="aarch64")
    ami_push_item = evolve(ami_push_item, release=release)

    mock_source.get.return_value.__enter__.return_value = [
        ami_push_item,
        vhd_push_item,
    ]

    command_tester.test(
        lambda: entry_point(MarketplacesVMPush),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--debug",
            "koji:https://fakekoji.com?vmi_build=unknown_build,ami_build",
        ],
    )


@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.starmap")
def test_push_item_no_mapped_arch(
    mock_starmap: mock.MagicMock,
    fake_source: mock.MagicMock,
    fake_cloud_instance: mock.MagicMock,
    ami_push_item: AmiPushItem,
    command_tester: CommandTester,
) -> None:
    """Ensure the push item with no arch in mappings for is not filtered out."""
    qr = QueryResponse.from_json(
        {
            "name": "fake-policy",
            "workflow": "stratosphere",
            "mappings": {
                "aws-na": [
                    {
                        "destination": "ffffffff-ffff-ffff-ffff-ffffffffffff",
                        "overwrite": False,
                        "restrict_version": False,
                    }
                ]
            },
        }
    )
    mock_starmap.query_image_by_name.return_value = qr

    command_tester.test(
        lambda: entry_point(MarketplacesVMPush),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--debug",
            "koji:https://fakekoji.com?vmi_build=ami_build",
        ],
    )


@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.starmap")
def test_push_item_no_destinations(
    mock_starmap: mock.MagicMock,
    fake_source: mock.MagicMock,
    fake_cloud_instance: mock.MagicMock,
    ami_push_item: AmiPushItem,
    command_tester: CommandTester,
) -> None:
    """Ensure the push item with no destinations is filtered out."""
    qr = QueryResponse.from_json(
        {
            "name": "fake-policy",
            "workflow": "stratosphere",
            "mappings": {"aws-na": []},
        }
    )
    mock_starmap.query_image_by_name.return_value = qr

    command_tester.test(
        lambda: entry_point(MarketplacesVMPush),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--debug",
            "koji:https://fakekoji.com?vmi_build=ami_build",
        ],
    )


@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.cloud_instance")
def test_push_item_fail_upload(
    mock_cloud_instance: mock.MagicMock,
    fake_source: mock.MagicMock,
    fake_starmap: mock.MagicMock,
    ami_push_item: AmiPushItem,
    vhd_push_item: VHDPushItem,
    command_tester: CommandTester,
) -> None:
    """Test a push which fails on upload for AWS."""
    mock_cloud_instance.return_value.upload.side_effect = [Exception("Random exception")]

    command_tester.test(
        lambda: entry_point(MarketplacesVMPush),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--debug",
            "koji:https://fakekoji.com?vmi_build=ami_build,azure_build",
        ],
    )
    starmap_calls = [mock.call(name="test-build", version="7.0") for _ in range(2)]
    fake_starmap.query_image_by_name.assert_has_calls(starmap_calls)
    # get_provider for AWS and Azure, upload and publish calls for "azure-na" only
    assert mock_cloud_instance.call_count == 3


@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.cloud_instance")
def test_push_item_fail_publish(
    mock_cloud_instance: mock.MagicMock,
    fake_source: mock.MagicMock,
    fake_starmap: mock.MagicMock,
    ami_push_item: AmiPushItem,
    vhd_push_item: VHDPushItem,
    command_tester: CommandTester,
) -> None:
    """Test a push which fails on publish for AWS."""

    class FakePublish(FakeCloudProvider):
        def _publish(self, push_item, nochannel, overwrite, **kwargs):
            raise Exception("Random exception")

    mock_cloud_instance.return_value = FakePublish()

    command_tester.test(
        lambda: entry_point(MarketplacesVMPush),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--debug",
            "koji:https://fakekoji.com?vmi_build=ami_build,azure_build",
        ],
    )
    starmap_calls = [mock.call(name="test-build", version="7.0") for _ in range(2)]
    fake_starmap.query_image_by_name.assert_has_calls(starmap_calls)
    # get_provider, upload calls for "aws-na", "aws-emea", "azure-na" with
    # publish calls only for "aws-na" and "azure-na"
    assert mock_cloud_instance.call_count == 14


@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.cloud_instance")
def test_push_overridden_destination(
    fake_cloud_instance: mock.MagicMock,
    fake_source: mock.MagicMock,
    fake_starmap: mock.MagicMock,
    command_tester: CommandTester,
) -> None:
    """Test a push success with the destinations overriden from command line."""

    class FakeCloudInstance:
        def upload(self, push_item, custom_tags=None, **kwargs):
            time.sleep(2)
            return push_item, True

        def pre_publish(self, push_item, **kwargs):
            return push_item, kwargs

        def publish(self, push_item, nochannel, overwrite, **_):
            return push_item, True

    fake_cloud_instance.return_value = FakeCloudInstance()

    command_tester.test(
        lambda: entry_point(MarketplacesVMPush),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--repo",
            "{"
            "\"mappings\": {"
            "    \"aws-na\": [{\"destination\": \"new_aws_na_destination\", \"overwrite\": false, \"restrict_version\": false}],"  # noqa: E501
            "    \"aws-emea\": [{\"destination\": \"new_aws_emea_destination\", \"overwrite\": true, \"restrict_version\": false}],"  # noqa: E501
            "    \"azure-na\": [ "
            "    {\"destination\": \"new_azure_destination1\", \"overwrite\": true, \"restrict_version\": false},"  # noqa: E501
            "    {\"destination\": \"new_azure_destination2\", \"overwrite\": false, \"restrict_version\": false}"  # noqa: E501
            "]"
            "},"
            "\"name\": \"sample-product\", \"workflow\": \"stratosphere\"}",
            "--debug",
            "koji:https://fakekoji.com?vmi_build=ami_build,azure_build",
        ],
    )


def test_no_credentials(
    fake_source: mock.MagicMock,
    fake_starmap: mock.MagicMock,
    ami_push_item: AmiPushItem,
    vhd_push_item: VHDPushItem,
    command_tester: CommandTester,
) -> None:
    """Raises an error that marketplaces credentials where not provided to process the images."""
    command_tester.test(
        lambda: entry_point(MarketplacesVMPush),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--debug",
            "koji:https://fakekoji.com?vmi_build=ami_build,azure_build",
        ],
    )


def test_no_source(command_tester: CommandTester, capsys: CaptureFixture) -> None:
    """Checks that exception is raised when the source is missing."""
    command_tester.test(
        lambda: entry_point(MarketplacesVMPush),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--debug",
        ],
    )
    _, err = capsys.readouterr()
    assert "error: too few arguments" or "error: the following arguments are required" in err


@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush._push_pre_publish")
@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush._push_upload")
@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush._push_publish")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
def test_empty_value_to_collect(
    mock_source: mock.MagicMock,
    mock_push: mock.MagicMock,
    mock_upload: mock.MagicMock,
    mock_prepublish: mock.MagicMock,
    fake_starmap: mock.MagicMock,
    ami_push_item: AmiPushItem,
    command_tester: CommandTester,
    starmap_query_aws: QueryResponse,
) -> None:
    """Ensure the JSONL exclude missing fields."""
    mock_source.get.return_value.__enter__.return_value = [ami_push_item]
    mock_push.return_value = [
        {
            "push_item": ami_push_item,
            "state": ami_push_item.state,
            "marketplace": None,
            "missing_key": None,
            "starmap_query": starmap_query_aws,
        }
    ]

    command_tester.test(
        lambda: entry_point(MarketplacesVMPush),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--debug",
            "koji:https://fakekoji.com?vmi_build=ami_build",
        ],
    )


@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush._push_pre_publish")
@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush._push_upload")
@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush._push_publish")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
def test_empty_items_not_allowed(
    mock_source: mock.MagicMock,
    mock_push: mock.MagicMock,
    mock_upload: mock.MagicMock,
    mock_prepublish: mock.MagicMock,
    fake_starmap: mock.MagicMock,
    command_tester: CommandTester,
) -> None:
    """Ensure the push fails when no push items are processed and skip is not allowed."""
    mock_source.get.return_value.__enter__.return_value = []
    mock_push.return_value = []

    command_tester.test(
        lambda: entry_point(MarketplacesVMPush),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--debug",
            "koji:https://fakekoji.com?vmi_build=ami_build",
        ],
    )


@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush._push_pre_publish")
@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush._push_upload")
@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush._push_publish")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
def test_empty_items_allowed(
    mock_source: mock.MagicMock,
    mock_push: mock.MagicMock,
    mock_upload: mock.MagicMock,
    mock_prepublish: mock.MagicMock,
    fake_starmap: mock.MagicMock,
    command_tester: CommandTester,
) -> None:
    """Ensure the push succeeds when no push items are processed and skip is allowed."""
    mock_source.get.return_value.__enter__.return_value = []
    mock_push.return_value = []

    mp = MarketplacesVMPush()

    command_tester.test(
        lambda: mp.main(allow_empty_targets=True),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--debug",
            "koji:https://fakekoji.com?vmi_build=ami_build",
        ],
    )


@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
def test_push_item_rhcos_gov(
    mock_source: mock.MagicMock,
    ami_push_item: AmiPushItem,
    fake_starmap: mock.MagicMock,
    fake_cloud_instance: mock.MagicMock,
    vhd_push_item: VHDPushItem,
    command_tester: CommandTester,
) -> None:
    """Ensure the push item for rhcos gov region is filtered out."""
    ami_push_item = evolve(ami_push_item, marketplace_name="aws")
    ami_push_item_gov = evolve(ami_push_item, src="ami-01")
    ami_push_item_gov = evolve(ami_push_item_gov, region="us-gov-1")
    vhd_push_item = evolve(vhd_push_item, marketplace_name="azure")

    mock_source.get.return_value.__enter__.return_value = [
        ami_push_item,
        ami_push_item_gov,
        vhd_push_item,
    ]
    command_tester.test(
        lambda: entry_point(MarketplacesVMPush),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--debug",
            "koji:https://fakekoji.com?vmi_build=unknown_build,ami_build",
        ],
    )
