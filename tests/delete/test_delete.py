# SPDX-License-Identifier: GPL-3.0-or-later
import base64
import json
import re
from datetime import date, datetime
from typing import Any, Dict, Generator, List
from unittest import mock

import pytest
from attrs import evolve
from pushsource import AmiPushItem, KojiBuildInfo, VHDPushItem, VMICloudInfo, VMIRelease

from pubtools._marketplacesvm.cloud_providers.base import CloudProvider
from pubtools._marketplacesvm.tasks.delete import VMDelete, entry_point
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
def fake_multiple_source(
    pub_response_ami: List[AmiPushItem], pub_response_azure: List[VHDPushItem]
) -> Generator[mock.MagicMock, None, None]:
    with mock.patch("pubtools._marketplacesvm.tasks.delete.command.Source") as m:
        m.get.return_value.__enter__.return_value = pub_response_ami + pub_response_azure
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


def test_delete_multiple_marketplaces(
    fake_multiple_source: mock.MagicMock,
    fake_cloud_instance: mock.MagicMock,
    command_tester: CommandTester,
):
    """Test a successfull delete with multiple marketplaces."""
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
            "rhcos-x86_64-414.92.202405201754-0,sample_product-1.0.1-1-x86_64,azure-testing",
            "pub:https://fakepub.com?task-id=12345",
        ],
    )

    fake_multiple_source.get.assert_called_once()

    # Assert both marketplaces are handled
    assert fake_cloud_instance.call_count == 3
    assert fake_cloud_instance.call_args_list[0].args == ('aws-china-storage',)
    assert fake_cloud_instance.call_args_list[1].args == ('aws-na',)
    assert fake_cloud_instance.call_args_list[2].args == ('azure-na',)


@mock.patch("pubtools._marketplacesvm.tasks.delete.VMDelete.cloud_instance")
def test_delete_images_already_deleted(
    mock_cloud_instance: mock.MagicMock,
    fake_azure_source: mock.MagicMock,
    command_tester: CommandTester,
):
    """Test a successfull delete with images already deleted."""

    class FakeMissingDeleteProvider(FakeCloudProvider):
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
            return push_item, (None, None)

    mock_cloud_instance.return_value = FakeMissingDeleteProvider()

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

    # Assert both marketplaces are handled
    assert "marking as MISSING" in command_tester._caplog.text


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

    fake_azure_source.get.assert_called_once()
    assert fake_cloud_instance.call_count == 1
    for call in fake_cloud_instance.call_args_list:
        assert call.args == ('azure-emea',)


@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
def test_delete_vhd_end_to_end(
    mock_collector_update_push_items: mock.MagicMock,
    requests_mocker,
    vhd_clouds_json: List[Dict[str, Any]],
    command_tester: CommandTester,
) -> None:

    fake_creds = {
        "marketplace_account": "azure-na",
        "auth": {
            "AZURE_TENANT_ID": "test",
            "AZURE_API_SECRET": "test",
            "AZURE_CLIENT_ID": "test",
            "AZURE_STORAGE_CONNECTION_STRING": "DefaultEndpointsProtocol=https;AccountName=test;AccountKey=test;EndpointSuffix=core.windows.net",  # noqa: E501
        },
    }
    fake_creds_str = json.dumps(fake_creds)
    encoded_fake_creds = base64.b64encode(fake_creds_str.encode('utf-8'))

    # Mocks for PubSource
    requests_mocker.register_uri(
        "GET", "https://fakepub.com/pub/task/938836/log/images.json", status_code=404
    )
    requests_mocker.register_uri(
        "GET", "https://fakepub.com/pub/task/938836/log/clouds.json?", json=vhd_clouds_json
    )

    # Mocks for Azure
    requests_mocker.register_uri("GET", "https://test.blob.core.windows.net/pubupload")
    requests_mocker.register_uri(
        "HEAD", "https://test.blob.core.windows.net/pubupload/TEST-PR-9.6_V2-20250910-x86_64-0"
    )
    requests_mocker.register_uri(
        "DELETE",
        "https://test.blob.core.windows.net/pubupload/TEST-PR-9.6_V2-20250910-x86_64-0",
        status_code=202,
    )

    command_tester.test(
        lambda: entry_point(VMDelete),
        [
            "test-delete",
            "--credentials",
            encoded_fake_creds.decode('ascii'),
            "--rhsm-url",
            "https://rhsm.com/test/api/",
            "--debug",
            "--builds",
            "test-pr-azure-9.6-20250909.4",
            "pub:https://fakepub.com?task_id=938836",
        ],
    )

    expected_dt = datetime.strptime("20250910", r"%Y%m%d")
    expected_date = date(expected_dt.year, expected_dt.month, expected_dt.day)

    expected_pi = VHDPushItem(
        name='test-pr-azure-9.6-20250909.4.x86_64.vhd.xz',
        state=State.DELETED,
        src='/mnt/koji/packages/test-pr-azure/9.6/20250909.4/images/test-pr-azure-9.6-20250909.4.x86_64.vhd.xz',  # noqa: E501
        dest=['test/test-pr9'],
        origin='RHBA-0000:123456',
        build='test-pr-azure-9.6-20250909.4',
        build_info=KojiBuildInfo(name='test-pr-azure', version='9.6', release='20250909.4'),
        release=VMIRelease(
            product='TEST-PR',
            date=expected_date,
            arch='x86_64',
            respin=0,
            version='9.6',
        ),
        description='',
        generation='V2',
        support_legacy=True,
        recommended_sizes=[],
        sas_uri='https://test.blob.core.windows.net/pubupload/test-pr-azure-9.6-20250909.4.x86_64.vhd?se=2028-09-10T09%3A25%3A03Z&sp=r&sv=2023-08-03&sr=b&sig=test',  # noqa: E501
    )
    mock_collector_update_push_items.assert_called_once()
    assert mock_collector_update_push_items.call_args[0][0] == [expected_pi]


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
