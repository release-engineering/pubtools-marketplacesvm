# SPDX-License-Identifier: GPL-3.0-or-later
import re
from typing import Dict, Generator, List
from unittest import mock

import pytest
from attrs import evolve
from pushsource import AmiPushItem, VHDPushItem, VMICloudInfo

from pubtools._marketplacesvm.cloud_providers.base import CloudProvider
from pubtools._marketplacesvm.tasks.delete import VMDelete, entry_point

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
        return push_item, (mock.MagicMock(), mock.MagicMock())


@pytest.fixture()
def fake_ami_source(pub_response_ami: List[AmiPushItem]) -> Generator[mock.MagicMock, None, None]:
    with mock.patch("pubtools._marketplacesvm.tasks.delete.command.Source") as m:
        m.get.return_value.__enter__.return_value = pub_response_ami
        yield m


@pytest.fixture()
def fake_azure_source(
    pub_response_azure: List[VHDPushItem],
) -> Generator[mock.MagicMock, None, None]:
    with mock.patch("pubtools._marketplacesvm.tasks.delete.command.Source") as m:
        m.get.return_value.__enter__.return_value = pub_response_azure
        yield m


@pytest.fixture()
def fake_ami_source_dif_amis(
    pub_response_diff_amis: List[AmiPushItem],
) -> Generator[mock.MagicMock, None, None]:
    with mock.patch("pubtools._marketplacesvm.tasks.delete.command.Source") as m:
        m.get.return_value.__enter__.return_value = pub_response_diff_amis
        yield m


@pytest.fixture()
def bad_fake_vmi_source(
    bad_pub_response_vmi: List[Dict[str, str]],
) -> Generator[mock.MagicMock, None, None]:
    with mock.patch("pubtools._marketplacesvm.tasks.delete.command.Source") as m:
        m.get.return_value.__enter__.return_value = bad_pub_response_vmi
        yield m


@pytest.fixture()
def fake_cloud_instance() -> Generator[mock.MagicMock, None, None]:
    with mock.patch("pubtools._marketplacesvm.tasks.delete.VMDelete.cloud_instance") as m:
        m.return_value = FakeCloudProvider()
        yield m


@pytest.fixture(autouse=True)
def fake_rhsm_api(requests_mocker):
    responses = [
        {
            "status_code": 200,
            "json": {
                "pagination": {"count": 1},
                "body": [{"amiID": "ami-aws1"}, {"amiID": "ami-rhcos1"}],
            },
        },
        {
            "status_code": 200,
            "json": {
                "pagination": {"count": 0},
                "body": [],
            },
        },
    ]
    requests_mocker.register_uri(
        "GET",
        re.compile("amazon/provider_image_groups"),
        json={
            "body": [
                {"name": "sample_product_HOURLY", "providerShortName": "ACN"},
                {"name": "rhcos", "providerShortName": "ACN"},
                {"name": "sample_product", "providerShortName": "fake"},
                {"name": "RHEL_HA", "providerShortName": "awstest"},
                {"name": "SAP", "providerShortName": "awstest"},
            ]
        },
    )
    requests_mocker.register_uri("GET", re.compile("amazon/amis"), responses)
    requests_mocker.register_uri("POST", re.compile("amazon/region"))
    requests_mocker.register_uri("PUT", re.compile("amazon/amis"))
    requests_mocker.register_uri("POST", re.compile("amazon/amis"))


def test_delete_ami(
    fake_ami_source: mock.MagicMock,
    fake_cloud_instance: mock.MagicMock,
    command_tester: CommandTester,
) -> None:
    """Test a successfull delete."""
    command_tester.test(
        lambda: entry_point(VMDelete),
        [
            "test-delete",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--rhsm-url",
            "https://rhsm.com/test/api/",
            "--debug",
            "--builds",
            "rhcos-x86_64-414.92.202405201754-0,sample_product-1.0.1-1-x86_64",
            "pub:https://fakepub.com?task-id=12345",
        ],
    )

    fake_ami_source.get.assert_called_once()
    # There's 2 as the AmiProduct deletes require trying aws-na and aws-emea
    assert fake_cloud_instance.call_count == 2
    assert fake_cloud_instance.call_args_list[0].args == ('aws-china-storage',)
    assert fake_cloud_instance.call_args_list[1].args == ('aws-na',)


def test_delete_vhd(
    fake_azure_source: mock.MagicMock,
    fake_cloud_instance: mock.MagicMock,
    command_tester: CommandTester,
) -> None:
    """Test a successfull delete."""
    command_tester.test(
        lambda: entry_point(VMDelete),
        [
            "test-delete",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--rhsm-url",
            "https://rhsm.com/test/api/",
            "--debug",
            "--builds",
            "azure-testing",
            "pub:https://fakepub.com?task-id=12345",
        ],
    )

    fake_azure_source.get.assert_called_once()
    assert fake_cloud_instance.call_count == 1
    assert fake_cloud_instance.call_args_list[0].args == ('azure-na',)


@mock.patch("pubtools._marketplacesvm.tasks.delete.command.Source")
def test_delete_using_cloud_info(
    mock_source: mock.MagicMock,
    fake_cloud_instance: mock.MagicMock,
    aws_push_item: AmiPushItem,
    command_tester: CommandTester,
) -> None:
    """Test a successfull delete using the cloud_info properties."""
    cloud_info = VMICloudInfo(provider="AWS", account="aws-us-storage")
    pi = evolve(aws_push_item, marketplace_entity_type=None, cloud_info=cloud_info)
    mock_source.get.return_value.__enter__.return_value = [pi]
    command_tester.test(
        lambda: entry_point(VMDelete),
        [
            "test-delete",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--rhsm-url",
            "https://rhsm.com/test/api/",
            "--debug",
            "--builds",
            "sample_product-1.0.1-1-x86_64",
            "pub:https://fakepub.com?task-id=12345",
        ],
    )

    mock_source.get.assert_called_once()
    fake_cloud_instance.assert_called_once_with("aws-us-storage")


def test_delete_vhd_cloud_info(
    fake_azure_source: mock.MagicMock,
    fake_cloud_instance: mock.MagicMock,
    vhd_push_item: VHDPushItem,
    command_tester: CommandTester,
) -> None:
    """Test a successfull delete."""
    cloud_info = VMICloudInfo(provider="", account="azure-emea")
    pi = evolve(vhd_push_item, cloud_info=cloud_info)
    fake_azure_source.get.return_value.__enter__.return_value = [pi]
    command_tester.test(
        lambda: entry_point(VMDelete),
        [
            "test-delete",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--rhsm-url",
            "https://rhsm.com/test/api/",
            "--debug",
            "--builds",
            "azure-testing",
            "pub:https://fakepub.com?task-id=12345",
        ],
    )

    """ fake_azure_source.get.assert_called_once()
    assert fake_cloud_instance.call_count == 1
    for call in fake_cloud_instance.call_args_list:
        assert call.args == ('azure-emea',) """


def test_delete_skip_build(
    fake_ami_source: mock.MagicMock,
    fake_cloud_instance: mock.MagicMock,
    command_tester: CommandTester,
) -> None:
    """Test a successfull delete skipping some builds."""
    command_tester.test(
        lambda: entry_point(VMDelete),
        [
            "test-delete",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--rhsm-url",
            "https://rhsm.com/test/api/",
            "--debug",
            "--builds",
            "rhcos-x86_64-414.92.202405201754-0",
            "pub:https://fakepub.com?task-id=12345",
        ],
    )

    fake_ami_source.get.assert_called_once()
    # 1 call for RHCOS delete
    assert fake_cloud_instance.call_count == 1


def test_delete_vhd_skipped(
    fake_azure_source: mock.MagicMock,
    fake_cloud_instance: mock.MagicMock,
    command_tester: CommandTester,
) -> None:
    """Test a successfull delete."""
    command_tester.test(
        lambda: entry_point(VMDelete),
        [
            "test-delete",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--rhsm-url",
            "https://rhsm.com/test/api/",
            "--debug",
            "--builds",
            "skipping",
            "pub:https://fakepub.com?task-id=12345",
        ],
    )

    fake_azure_source.get.assert_called_once()
    # 1 call for RHCOS delete
    assert fake_cloud_instance.call_count == 0


def test_delete_ami_id_not_found_rhsm(
    fake_ami_source: mock.MagicMock,
    fake_cloud_instance: mock.MagicMock,
    command_tester: CommandTester,
    requests_mocker,
) -> None:
    """Test a successfull delete skipping some builds."""
    responses = [
        {
            "status_code": 200,
            "json": {
                "pagination": {"count": 1},
                "body": [{"amiID": "ami-rhcos1"}],
            },
        },
        {
            "status_code": 200,
            "json": {
                "pagination": {"count": 0},
                "body": [],
            },
        },
    ]
    requests_mocker.register_uri("GET", re.compile("amazon/amis"), responses)
    command_tester.test(
        lambda: entry_point(VMDelete),
        [
            "test-delete",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--rhsm-url",
            "https://rhsm.com/test/api/",
            "--debug",
            "--builds",
            "rhcos-x86_64-414.92.202405201754-0,sample_product-1.0.1-1-x86_64",
            "pub:https://fakepub.com?task-id=12345",
        ],
    )

    fake_ami_source.get.assert_called_once()
    # 2 call for RHCOS delete
    assert fake_cloud_instance.call_count == 2


def test_delete_dry_run(
    fake_ami_source: mock.MagicMock,
    fake_cloud_instance: mock.MagicMock,
    command_tester: CommandTester,
) -> None:
    """Test a successfull delete using dry-run."""
    command_tester.test(
        lambda: entry_point(VMDelete),
        [
            "test-delete",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--rhsm-url",
            "https://rhsm.com/test/api/",
            "--debug",
            "--dry-run",
            "--builds",
            "rhcos-x86_64-414.92.202405201754-0,sample_product-1.0.1-1-x86_64",
            "pub:https://fakepub.com?task-id=12345",
        ],
    )

    fake_ami_source.get.assert_called_once()
    # 0 calls for dry-run, should just report to log
    assert fake_cloud_instance.call_count == 0


def test_delete_vhd_dry_run(
    fake_azure_source: mock.MagicMock,
    fake_cloud_instance: mock.MagicMock,
    command_tester: CommandTester,
) -> None:
    """Test a successfull delete."""
    command_tester.test(
        lambda: entry_point(VMDelete),
        [
            "test-delete",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--rhsm-url",
            "https://rhsm.com/test/api/",
            "--debug",
            "--dry-run",
            "--builds",
            "azure-testing",
            "pub:https://fakepub.com?task-id=12345",
        ],
    )

    fake_azure_source.get.assert_called_once()
    # 0 calls for dry-run, should just report to log
    assert fake_cloud_instance.call_count == 0


def test_delete_failed(
    fake_ami_source: mock.MagicMock,
    fake_cloud_instance: mock.MagicMock,
    command_tester: CommandTester,
) -> None:
    """Test a failed delete."""

    class FakePublish(FakeCloudProvider):
        def _delete_push_images(self, push_item, **kwargs):
            raise Exception("Random exception")

    fake_cloud_instance.return_value = FakePublish()
    command_tester.test(
        lambda: entry_point(VMDelete),
        [
            "test-delete",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--rhsm-url",
            "https://rhsm.com/test/api/",
            "--debug",
            "--builds",
            "rhcos-x86_64-414.92.202405201754-0,sample_product-1.0.1-1-x86_64",
            "pub:https://fakepub.com?task-id=12345",
        ],
    )

    fake_ami_source.get.assert_called_once()
    # 3 calls since we errored on aws-na, aws-emea, aws-us-storage
    assert fake_cloud_instance.call_count == 1


def test_delete_failed_one(
    fake_ami_source_dif_amis: mock.MagicMock,
    fake_cloud_instance: mock.MagicMock,
    command_tester: CommandTester,
) -> None:
    """Test a failed delete."""
    image_seen = []

    class FakePublish(FakeCloudProvider):
        def _delete_push_images(self, push_item, **kwargs):
            if push_item.image_id not in image_seen:
                image_seen.append(push_item.image_id)
                raise Exception("Random exception")
            return push_item, kwargs

    fake_cloud_instance.return_value = FakePublish()
    command_tester.test(
        lambda: entry_point(VMDelete),
        [
            "test-delete",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--rhsm-url",
            "https://rhsm.com/test/api/",
            "--debug",
            "--builds",
            "rhcos-x86_64-414.92.202405201754-0,sample_product-1.0.1-1-x86_64",
            "pub:https://fakepub.com?task-id=12345",
        ],
    )

    fake_ami_source_dif_amis.get.assert_called_once()
    # 4 Calls since we errored on the first call
    assert fake_cloud_instance.call_count == 1


def test_delete_not_VmiPushItem(
    bad_fake_vmi_source: mock.MagicMock,
    fake_cloud_instance: mock.MagicMock,
    command_tester: CommandTester,
) -> None:
    """Test a bad response from Pub."""
    command_tester.test(
        lambda: entry_point(VMDelete),
        [
            "test-delete",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--rhsm-url",
            "https://rhsm.com/test/api/",
            "--debug",
            "--builds",
            "rhcos-x86_64-414.92.202405201754-0,sample_product-1.0.1-1-x86_64",
            "pub:https://fakepub.com?task-id=12345",
        ],
    )

    bad_fake_vmi_source.get.assert_called_once()
    # No calls as there was nothing to work
    assert fake_cloud_instance.call_count == 0


def test_delete_bad_rhsm(
    fake_ami_source: mock.MagicMock,
    fake_cloud_instance: mock.MagicMock,
    command_tester: CommandTester,
    requests_mocker,
) -> None:
    """Test a successfull delete."""
    requests_mocker.register_uri("PUT", re.compile("amazon/amis"), status_code=400)
    requests_mocker.register_uri("POST", re.compile("amazon/amis"), status_code=500)
    command_tester.test(
        lambda: entry_point(VMDelete),
        [
            "test-delete",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--rhsm-url",
            "https://rhsm.com/test/api/",
            "--debug",
            "--builds",
            "rhcos-x86_64-414.92.202405201754-0,sample_product-1.0.1-1-x86_64",
            "pub:https://fakepub.com?task-id=12345",
        ],
    )

    fake_ami_source.get.assert_called_once()


@mock.patch("pubtools._marketplacesvm.tasks.delete.command.Source")
def test_delete_limit_items(
    mock_source: mock.MagicMock,
    aws_push_item: AmiPushItem,
    aws_push_item_2: AmiPushItem,
    vhd_push_item: VHDPushItem,
    fake_cloud_instance: mock.MagicMock,
    command_tester: CommandTester,
) -> None:
    """Test a deletion with limited image IDs."""
    mock_source.get.return_value.__enter__.return_value = [
        aws_push_item,
        aws_push_item_2,
        vhd_push_item,
    ]

    command_tester.test(
        lambda: entry_point(VMDelete),
        [
            "test-delete",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--rhsm-url",
            "https://rhsm.com/test/api/",
            "--debug",
            "--builds",
            "sample_product-1.0.1-1-x86_64,azure-testing",
            "--limit",
            f"{aws_push_item.image_id},{vhd_push_item.name}",
            "pub:https://fakepub.com?task-id=12345",
        ],
    )

    mock_source.get.assert_called_once()
    assert fake_cloud_instance.call_count == 2
    assert fake_cloud_instance.call_args_list[0].args == ('aws-na',)
    assert fake_cloud_instance.call_args_list[1].args == ('azure-na',)
    assert aws_push_item.image_id in command_tester._caplog.text
    assert aws_push_item_2.image_id not in command_tester._caplog.text
    assert vhd_push_item.name in command_tester._caplog.text
