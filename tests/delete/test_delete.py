# SPDX-License-Identifier: GPL-3.0-or-later
import re
from typing import Dict, Generator, List
from unittest import mock

import pytest
from pushsource import AmiPushItem

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
        return push_item


@pytest.fixture()
def fake_source(pub_response: List[AmiPushItem]) -> Generator[mock.MagicMock, None, None]:
    with mock.patch("pubtools._marketplacesvm.tasks.delete.command.Source") as m:
        m.get.return_value.__enter__.return_value = pub_response
        yield m


@pytest.fixture()
def fake_source_dif_amis(
    pub_response_diff_amis: List[AmiPushItem],
) -> Generator[mock.MagicMock, None, None]:
    with mock.patch("pubtools._marketplacesvm.tasks.delete.command.Source") as m:
        m.get.return_value.__enter__.return_value = pub_response_diff_amis
        yield m


@pytest.fixture()
def bad_fake_source(
    bad_pub_response: List[Dict[str, str]]
) -> Generator[mock.MagicMock, None, None]:
    with mock.patch("pubtools._marketplacesvm.tasks.delete.command.Source") as m:
        m.get.return_value.__enter__.return_value = bad_pub_response
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


def test_delete(
    fake_source: mock.MagicMock,
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

    fake_source.get.assert_called_once()
    # There's 2 as the AmiProduct deletes require trying aws-na and aws-emea
    assert fake_cloud_instance.call_count == 2


def test_delete_skip_build(
    fake_source: mock.MagicMock,
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

    fake_source.get.assert_called_once()
    # 1 call for RHCOS delete
    assert fake_cloud_instance.call_count == 1


def test_delete_ami_id_not_found_rhsm(
    fake_source: mock.MagicMock,
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

    fake_source.get.assert_called_once()
    # 2 call for RHCOS delete
    assert fake_cloud_instance.call_count == 2


def test_delete_dry_run(
    fake_source: mock.MagicMock,
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

    fake_source.get.assert_called_once()
    # 0 calls for dry-run, should just report to log
    assert fake_cloud_instance.call_count == 0


def test_delete_failed(
    fake_source: mock.MagicMock,
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

    fake_source.get.assert_called_once()
    # 3 calls since we errored on aws-na, aws-emea, aws-us-storage
    assert fake_cloud_instance.call_count == 3


def test_delete_failed_one(
    fake_source_dif_amis: mock.MagicMock,
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
            return push_item

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

    fake_source_dif_amis.get.assert_called_once()
    # 4 Calls since we errored on the first call
    assert fake_cloud_instance.call_count == 4


def test_delete_not_AmiPushItem(
    bad_fake_source: mock.MagicMock,
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

    bad_fake_source.get.assert_called_once()
    # No calls as there was nothing to work
    assert fake_cloud_instance.call_count == 0


def test_delete_bad_rhsm(
    fake_source: mock.MagicMock,
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

    fake_source.get.assert_called_once()
