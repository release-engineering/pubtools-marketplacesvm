# SPDX-License-Identifier: GPL-3.0-or-later
import json
import logging
from copy import copy
from datetime import datetime
from typing import Any, Dict, Generator
from unittest import mock

import pytest
from _pytest.capture import CaptureFixture
from attrs import evolve
from pushsource import AmiPushItem, AmiRelease, KojiBuildInfo, PushItem, VHDPushItem
from starmap_client.models import QueryResponseContainer, QueryResponseEntity

from pubtools._marketplacesvm.cloud_providers.base import CloudProvider
from pubtools._marketplacesvm.cloud_providers.ms_azure import AzureProvider
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
def fake_source(
    ami_push_item: AmiPushItem, vhd_push_item: VHDPushItem
) -> Generator[mock.MagicMock, None, None]:
    with mock.patch("pubtools._marketplacesvm.tasks.push.command.Source") as m:
        m.get.return_value.__enter__.return_value = [ami_push_item, vhd_push_item]
        yield m


@pytest.fixture()
def fake_starmap(
    starmap_query_aws: QueryResponseEntity, starmap_query_azure: QueryResponseEntity
) -> Generator[mock.MagicMock, None, None]:
    with mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.starmap") as m:
        m.query_image_by_name.side_effect = [
            QueryResponseContainer([x]) for x in [starmap_query_aws, starmap_query_azure]
        ]

        yield m


@pytest.fixture()
def fake_cloud_instance() -> Generator[mock.MagicMock, None, None]:
    with mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.cloud_instance") as m:
        m.return_value = FakeCloudProvider()
        yield m


def _check_collector_update_push_items(
    mock_collector_update_push_items: mock.MagicMock,
    expected_ami_pi_count: int,
    expected_vhd_pi_count: int,
) -> None:
    assert mock_collector_update_push_items.call_count == 1
    collected_push_items = mock_collector_update_push_items.call_args[0][0]
    assert len(collected_push_items) == expected_ami_pi_count + expected_vhd_pi_count

    assert expected_ami_pi_count == len(
        [i for i in collected_push_items if isinstance(i, AmiPushItem)]
    )
    assert expected_vhd_pi_count == len(
        [i for i in collected_push_items if isinstance(i, VHDPushItem)]
    )


@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
def test_do_push(
    mock_collector_update_push_items: mock.MagicMock,
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
    assert fake_cloud_instance.call_count == 13

    _check_collector_update_push_items(
        mock_collector_update_push_items, expected_ami_pi_count=2, expected_vhd_pi_count=3
    )


@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.cloud_instance")
@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.starmap")
def test_do_push_ami_correct_id(
    mock_starmap: mock.MagicMock,
    mock_source: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
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
            push_item = evolve(push_item, image_id=self.amis.pop(0))
            return push_item, True

        def _pre_publish(self, push_item, **kwargs):
            return push_item, kwargs

        def _publish(self, push_item, nochannel, overwrite, **kwargs):
            # This log will allow us to identify whether the image_id is the expected
            self.log.debug(f"Pushing {push_item.name} with image: {push_item.image_id}")
            return push_item, nochannel

    mock_cloud_instance.return_value = FakeAWSProvider()

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
                            "overwrite": False,
                            "restrict_version": True,
                            "restrict_major": 3,
                            "restrict_minor": 1,
                        },
                    ]
                },
                "aws-emea": {
                    "destinations": [
                        {
                            "destination": "EMEA-DESTINATION",
                            "overwrite": False,
                            "restrict_version": True,
                            "restrict_major": 3,
                            "restrict_minor": 1,
                        },
                    ]
                },
            },
        }
    )
    mock_starmap.query_image_by_name.return_value = QueryResponseContainer([qre])
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
    assert mock_cloud_instance.call_count == 6

    _check_collector_update_push_items(
        mock_collector_update_push_items, expected_ami_pi_count=2, expected_vhd_pi_count=0
    )


@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.cloud_instance")
@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.starmap")
def test_do_push_azure_correct_sas(
    mock_starmap: mock.MagicMock,
    mock_source: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
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
            push_item = evolve(push_item, sas_uri=self.vhds.pop(0))
            return push_item, True

        def _pre_publish(self, push_item, **kwargs):
            return push_item, kwargs

        def _publish(self, push_item, nochannel, overwrite, **kwargs):
            # This log will allow us to identify whether the sas_uri is the expected
            self.log.debug(f"Pushing {push_item.name} with image: {push_item.sas_uri}")
            return push_item, nochannel

    mock_cloud_instance.return_value = FakeAzureProvider()

    qre = QueryResponseEntity.from_json(
        {
            "name": "fake-policy",
            "workflow": "stratosphere",
            "cloud": "azure",
            "mappings": {
                "azure-na": {
                    "destinations": [
                        {
                            "destination": "NA-DESTINATION",
                            "overwrite": False,
                            "restrict_version": False,
                        },
                    ]
                },
                "azure-emea": {
                    "destinations": [
                        {
                            "destination": "EMEA-DESTINATION",
                            "overwrite": False,
                            "restrict_version": False,
                        },
                    ]
                },
            },
        }
    )
    mock_starmap.query_image_by_name.return_value = QueryResponseContainer([qre])
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
    assert mock_cloud_instance.call_count == 6

    _check_collector_update_push_items(
        mock_collector_update_push_items, expected_ami_pi_count=0, expected_vhd_pi_count=2
    )


@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.cloud_instance")
@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.starmap")
def test_do_push_azure_compare_base_sas(
    mock_starmap: mock.MagicMock,
    mock_source: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
    mock_cloud_instance: mock.MagicMock,
    vhd_push_item: VHDPushItem,
    command_tester: CommandTester,
) -> None:
    """Test a successful push for Azure which has the base SAS URI comparison only."""
    azure_na = "fake-azure-sas-for-na"
    azure_emea = "fake-azure-sas-for-emea"

    class FakeAzureProvider(FakeCloudProvider):
        vhds = [azure_na, azure_emea]
        log = logging.getLogger("pubtools.marketplacesvm")

        def _upload(self, push_item, custom_tags=None, **kwargs):
            push_item = evolve(push_item, sas_uri=self.vhds.pop(0))
            return push_item, True

        def _pre_publish(self, push_item, **kwargs):
            self.log.debug(
                f"Associating {push_item.name} with image {push_item.sas_uri} and args: {kwargs}"
            )
            return push_item, kwargs

        def _publish(self, push_item, nochannel, overwrite, **kwargs):
            # This log will allow us to identify whether the sas_uri is the expected
            self.log.debug(f"Pushing {push_item.name} with image: {push_item.sas_uri}")
            # This one will allos us to identify whether the arguments are expected,
            # mainly to ensure `{'check_base_sas_only': True}`
            self.log.debug(f"Pushing {push_item.name} with args: {kwargs}")
            return push_item, nochannel

    mock_cloud_instance.return_value = FakeAzureProvider()

    qre = QueryResponseEntity.from_json(
        {
            "name": "fake-policy",
            "workflow": "stratosphere",
            "cloud": "azure",
            "mappings": {
                "azure-na": {
                    "destinations": [
                        {
                            "destination": "NA-DESTINATION",
                            "overwrite": False,
                            "restrict_version": False,
                            "vhd_check_base_sas_only": True,
                        },
                    ]
                },
                "azure-emea": {
                    "destinations": [
                        {
                            "destination": "EMEA-DESTINATION",
                            "overwrite": False,
                            "restrict_version": False,
                            "vhd_check_base_sas_only": True,
                        },
                    ]
                },
            },
        }
    )
    mock_starmap.query_image_by_name.return_value = QueryResponseContainer([qre])
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
    assert mock_cloud_instance.call_count == 6


@mock.patch("pubtools._marketplacesvm.cloud_providers.ms_azure.AzurePublishMetadata")
@mock.patch("pubtools._marketplacesvm.cloud_providers.ms_azure.AzurePublishService")
@mock.patch("pubtools._marketplacesvm.cloud_providers.ms_azure.AzureUploadMetadata")
@mock.patch("pubtools._marketplacesvm.cloud_providers.ms_azure.AzureUploadService")
@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.cloud_instance")
@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.starmap")
def test_do_push_azure_expected_publishing_metadata_applied(
    mock_starmap: mock.MagicMock,
    mock_source: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
    mock_cloud_instance: mock.MagicMock,
    mock_upload_svc: mock.MagicMock,
    mock_upload_meta: mock.MagicMock,
    mock_publish_svc: mock.MagicMock,
    mock_publish_meta: mock.MagicMock,
    vhd_push_item: VHDPushItem,
    command_tester: CommandTester,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test a successful push for Azure which has the proper publishing metadata included."""
    # Prepare mocks
    mock_disk_version = mock.MagicMock()
    upload_svc_obj = mock.MagicMock()
    publish_svc_obj = mock.MagicMock()
    publish_svc_obj.diff_two_offers.return_value = {}
    mock_upload_svc.return_value = upload_svc_obj
    mock_upload_svc.from_connection_string.return_value = upload_svc_obj
    mock_publish_svc.return_value = publish_svc_obj
    patched_azure = AzureProvider(credentials=mock.MagicMock())
    mock_cloud_instance.return_value = patched_azure

    # Fill missing values
    mock_disk_version.return_value = "7.0.2025080716"
    monkeypatch.setattr(patched_azure, "_generate_disk_version", mock_disk_version)
    upload_svc_obj.get_blob_sas_uri.return_value = "https://fake-sas-uri.blob.windows.net"
    vhd_push_item = evolve(vhd_push_item, src="source_azure_push_item")

    # Include StArMap query
    qre = QueryResponseEntity.from_json(
        {
            "name": "fake-policy",
            "workflow": "stratosphere",
            "cloud": "azure",
            "mappings": {
                "azure-na": {
                    "destinations": [
                        {
                            "destination": "NA-DESTINATION",
                            "overwrite": False,
                            "restrict_version": False,
                            "vhd_check_base_sas_only": True,
                            "meta": {
                                "generation": "V2",
                                "support_legacy": True,
                                "modular_push": True,
                            },
                        },
                    ]
                },
                "azure-emea": {
                    "destinations": [
                        {
                            "destination": "EMEA-DESTINATION",
                            "overwrite": False,
                            "restrict_version": False,
                            "vhd_check_base_sas_only": True,
                            "meta": {
                                "generation": "V2",
                                "support_legacy": True,
                                "modular_push": False,
                            },
                        },
                    ]
                },
            },
        }
    )
    mock_starmap.query_image_by_name.return_value = QueryResponseContainer([qre])
    mock_source.get.return_value.__enter__.return_value = [vhd_push_item]

    # Expected results:
    expected_upload_metadata = {
        'image_path': 'source_azure_push_item',
        'image_name': 'sample-product-7.0_V2-20250402-x86_64-1',
        'container': 'pubupload',
        'description': '',
        'arch': 'x86_64',
        'tags': {
            'arch': 'x86_64',
            'buildid': 'None',
            'name': 'test-build',
            'nvra': 'test-build-7.0-20230101.x86_64',
            'release': '20230101',
            'version': '7.0',
        },
    }
    expected_publish_metadata_na: Dict[str, Any] = {
        'disk_version': '7.0.2025080716',
        'sku_id': None,
        'generation': 'V2',
        'support_legacy': True,
        'recommended_sizes': [],
        'legacy_sku_id': None,
        'image_path': 'https://fake-sas-uri.blob.windows.net',
        'architecture': 'x86_64',
        'destination': 'NA-DESTINATION',
        'keepdraft': True,
        'overwrite': False,
        'check_base_sas_only': True,
        'modular_push': True,
    }
    expected_publish_metadata_na_push = copy(expected_publish_metadata_na)
    expected_publish_metadata_na_push["keepdraft"] = False
    expected_publish_metadata_emea = copy(expected_publish_metadata_na)
    expected_publish_metadata_emea["destination"] = "EMEA-DESTINATION"
    expected_publish_metadata_emea["modular_push"] = False
    expected_publish_metadata_emea_push = copy(expected_publish_metadata_emea)
    expected_publish_metadata_emea_push["keepdraft"] = False

    # Test
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
    mock_upload_meta.assert_has_calls([mock.call(**expected_upload_metadata) for _ in range(2)])
    mock_publish_meta.assert_has_calls(
        [
            mock.call(**expected_publish_metadata_na),
            mock.call(**expected_publish_metadata_emea),
            mock.call(**expected_publish_metadata_na_push),
            mock.call(**expected_publish_metadata_emea_push),
        ]
    )


@mock.patch("pubtools._marketplacesvm.cloud_providers.ms_azure.AzurePublishMetadata")
@mock.patch("pubtools._marketplacesvm.cloud_providers.ms_azure.AzurePublishService")
@mock.patch("pubtools._marketplacesvm.cloud_providers.ms_azure.AzureUploadMetadata")
@mock.patch("pubtools._marketplacesvm.cloud_providers.ms_azure.AzureUploadService")
@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.cloud_instance")
@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.starmap")
def test_do_push_azure_modular_push_global_metadata(
    mock_starmap: mock.MagicMock,
    mock_source: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
    mock_cloud_instance: mock.MagicMock,
    mock_upload_svc: mock.MagicMock,
    mock_upload_meta: mock.MagicMock,
    mock_publish_svc: mock.MagicMock,
    mock_publish_meta: mock.MagicMock,
    vhd_push_item: VHDPushItem,
    command_tester: CommandTester,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test a successful push for Azure which has the modular_push in global metadata."""
    # Prepare mocks
    mock_disk_version = mock.MagicMock()
    upload_svc_obj = mock.MagicMock()
    publish_svc_obj = mock.MagicMock()
    publish_svc_obj.diff_two_offers.return_value = {}
    mock_upload_svc.return_value = upload_svc_obj
    mock_upload_svc.from_connection_string.return_value = upload_svc_obj
    mock_publish_svc.return_value = publish_svc_obj
    patched_azure = AzureProvider(credentials=mock.MagicMock())
    mock_cloud_instance.return_value = patched_azure

    # Fill missing values
    mock_disk_version.return_value = "7.0.2025080716"
    monkeypatch.setattr(patched_azure, "_generate_disk_version", mock_disk_version)
    upload_svc_obj.get_blob_sas_uri.return_value = "https://fake-sas-uri.blob.windows.net"
    vhd_push_item = evolve(vhd_push_item, src="source_azure_push_item")

    # Include StArMap query
    qre = QueryResponseEntity.from_json(
        {
            "name": "fake-policy",
            "workflow": "stratosphere",
            "cloud": "azure",
            "meta": {
                "modular_push": True,  # This should apply for both NA and EMEA
            },
            "mappings": {
                "azure-na": {
                    "destinations": [
                        {
                            "destination": "NA-DESTINATION",
                            "overwrite": False,
                            "restrict_version": False,
                            "vhd_check_base_sas_only": True,
                            "meta": {
                                "generation": "V2",
                                "support_legacy": True,
                            },
                        },
                    ]
                },
                "azure-emea": {
                    "destinations": [
                        {
                            "destination": "EMEA-DESTINATION",
                            "overwrite": False,
                            "restrict_version": False,
                            "vhd_check_base_sas_only": True,
                            "meta": {
                                "generation": "V2",
                                "support_legacy": True,
                            },
                        },
                    ]
                },
            },
        }
    )
    mock_starmap.query_image_by_name.return_value = QueryResponseContainer([qre])
    mock_source.get.return_value.__enter__.return_value = [vhd_push_item]

    # Expected results:
    expected_upload_metadata = {
        'image_path': 'source_azure_push_item',
        'image_name': 'sample-product-7.0_V2-20250402-x86_64-1',
        'container': 'pubupload',
        'description': '',
        'arch': 'x86_64',
        'tags': {
            'arch': 'x86_64',
            'buildid': 'None',
            'name': 'test-build',
            'nvra': 'test-build-7.0-20230101.x86_64',
            'release': '20230101',
            'version': '7.0',
        },
    }
    expected_publish_metadata_na: Dict[str, Any] = {
        'disk_version': '7.0.2025080716',
        'sku_id': None,
        'generation': 'V2',
        'support_legacy': True,
        'recommended_sizes': [],
        'legacy_sku_id': None,
        'image_path': 'https://fake-sas-uri.blob.windows.net',
        'architecture': 'x86_64',
        'destination': 'NA-DESTINATION',
        'keepdraft': True,
        'overwrite': False,
        'check_base_sas_only': True,
        'modular_push': True,
    }
    expected_publish_metadata_na_push = copy(expected_publish_metadata_na)
    expected_publish_metadata_na_push["keepdraft"] = False
    expected_publish_metadata_emea = copy(expected_publish_metadata_na)
    expected_publish_metadata_emea["destination"] = "EMEA-DESTINATION"
    expected_publish_metadata_emea_push = copy(expected_publish_metadata_emea)
    expected_publish_metadata_emea_push["keepdraft"] = False

    # Test
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
    mock_upload_meta.assert_has_calls([mock.call(**expected_upload_metadata) for _ in range(2)])
    mock_publish_meta.assert_has_calls(
        [
            mock.call(**expected_publish_metadata_na),
            mock.call(**expected_publish_metadata_emea),
            mock.call(**expected_publish_metadata_na_push),
            mock.call(**expected_publish_metadata_emea_push),
        ]
    )


@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
def test_do_push_prepush(
    mock_collector_update_push_items: mock.MagicMock,
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
    fake_cloud_instance.assert_has_calls([mock.call(x) for x in ["aws-na", "aws-emea", "azure-na"]])

    _check_collector_update_push_items(
        mock_collector_update_push_items, expected_ami_pi_count=2, expected_vhd_pi_count=3
    )


@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
def test_not_vmi_push_item(
    mock_source: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
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
    assert fake_cloud_instance.call_count == 6

    _check_collector_update_push_items(
        mock_collector_update_push_items, expected_ami_pi_count=2, expected_vhd_pi_count=0
    )


@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
def test_push_item_wrong_arch(
    mock_source: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
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

    _check_collector_update_push_items(
        mock_collector_update_push_items, expected_ami_pi_count=0, expected_vhd_pi_count=3
    )


@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.starmap")
def test_push_item_no_mapped_arch(
    mock_starmap: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
    fake_source: mock.MagicMock,
    fake_cloud_instance: mock.MagicMock,
    ami_push_item: AmiPushItem,
    command_tester: CommandTester,
) -> None:
    """Ensure the push item with no arch in mappings for is not filtered out."""
    qre = QueryResponseEntity.from_json(
        {
            "name": "test-build",
            "workflow": "stratosphere",
            "cloud": "aws",
            "mappings": {
                "aws-na": {
                    "destinations": [
                        {
                            "destination": "ffffffff-ffff-ffff-ffff-ffffffffffff",
                            "overwrite": False,
                            "restrict_version": False,
                        }
                    ],
                }
            },
        }
    )
    mock_starmap.query_image_by_name.return_value = QueryResponseContainer([qre])

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

    _check_collector_update_push_items(
        mock_collector_update_push_items, expected_ami_pi_count=1, expected_vhd_pi_count=0
    )


@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
def test_push_multiple_destinations_with_arch(
    mock_source: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
    fake_cloud_instance: mock.MagicMock,
    command_tester: CommandTester,
    ami_push_item: AmiPushItem,
    vhd_push_item: VHDPushItem,
) -> None:
    """Ensure that a push with will ignore destinations without matching arch."""
    binfo = KojiBuildInfo(name="sample-product", version="7.0", release="20230101")
    ami_push_item = evolve(ami_push_item, build_info=binfo)
    vhd_push_item = evolve(vhd_push_item, build_info=binfo)
    mock_source.get.return_value.__enter__.return_value = [ami_push_item, vhd_push_item]

    policy = [
        {
            "mappings": {
                "azure-na": {
                    "destinations": [
                        {
                            "destination": "azure-destination-for-x64",
                            "overwrite": True,
                            "restrict_version": False,
                            "architecture": "x86_64",
                        },
                        {
                            "destination": "azure-destination-for-arm",
                            "overwrite": False,
                            "restrict_version": False,
                            "architecture": "aarch64",
                        },
                    ]
                },
            },
            "name": "sample-product",
            "workflow": "stratosphere",
            "cloud": "azure",
        },
        {
            "mappings": {
                "aws-na": {
                    "destinations": [
                        {
                            "destination": "aws-destination-for-x64",
                            "overwrite": False,
                            "restrict_version": False,
                            "architecture": "x86_64",
                        },
                        {
                            "destination": "aws-destination-for-arm",
                            "overwrite": False,
                            "restrict_version": False,
                            "architecture": "aarch64",
                        },
                    ]
                },
            },
            "name": "sample-product",
            "workflow": "stratosphere",
            "cloud": "aws",
        },
    ]

    command_tester.test(
        lambda: entry_point(MarketplacesVMPush),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--repo",
            json.dumps(policy),
            "--offline",
            "--debug",
            "koji:https://fakekoji.com?vmi_build=ami_build,azure_build",
        ],
    )

    assert mock_collector_update_push_items.call_count == 1

    collected_push_items = mock_collector_update_push_items.call_args[0][0]
    expected_destinations = [
        "aws-destination-for-x64",
        "azure-destination-for-x64",
    ]
    collected_destinations = []
    for pi in collected_push_items:
        collected_destinations.extend(pi.dest)

    assert collected_destinations == expected_destinations


@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.starmap")
def test_push_item_no_destinations(
    mock_starmap: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
    fake_source: mock.MagicMock,
    fake_cloud_instance: mock.MagicMock,
    ami_push_item: AmiPushItem,
    command_tester: CommandTester,
) -> None:
    """Ensure the push item with no destinations is filtered out."""
    qr = QueryResponseEntity.from_json(
        {
            "name": "test-build",
            "workflow": "stratosphere",
            "cloud": "aws",
            "mappings": {"aws-na": {"destinations": []}},
        }
    )
    mock_starmap.query_image_by_name.return_value = QueryResponseContainer([qr])

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

    _check_collector_update_push_items(
        mock_collector_update_push_items, expected_ami_pi_count=0, expected_vhd_pi_count=0
    )


@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.cloud_instance")
def test_push_item_fail_upload(
    mock_cloud_instance: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
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

    _check_collector_update_push_items(
        mock_collector_update_push_items, expected_ami_pi_count=2, expected_vhd_pi_count=3
    )


@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.cloud_instance")
def test_push_item_fail_publish(
    mock_cloud_instance: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
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
    assert mock_cloud_instance.call_count == 13

    _check_collector_update_push_items(
        mock_collector_update_push_items, expected_ami_pi_count=2, expected_vhd_pi_count=3
    )


@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
def test_push_overridden_destination(
    mock_source: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
    fake_cloud_instance: mock.MagicMock,
    command_tester: CommandTester,
    ami_push_item: AmiPushItem,
    vhd_push_item: VHDPushItem,
) -> None:
    """Test a push success with the destinations overriden from command line."""
    binfo = KojiBuildInfo(name="sample-product", version="7.0", release="20230101")
    ami_push_item = evolve(ami_push_item, build_info=binfo)
    vhd_push_item = evolve(vhd_push_item, build_info=binfo)
    mock_source.get.return_value.__enter__.return_value = [ami_push_item, vhd_push_item]

    policy = [
        {
            "mappings": {
                "aws-na": {
                    "destinations": [
                        {
                            "destination": "new_aws_na_destination",
                            "overwrite": False,
                            "restrict_version": False,
                        }
                    ]
                },
                "aws-emea": {
                    "destinations": [
                        {
                            "destination": "new_aws_emea_destination",
                            "overwrite": True,
                            "restrict_version": False,
                        }
                    ]
                },
            },
            "name": "sample-product",
            "workflow": "stratosphere",
            "cloud": "aws",
        },
        {
            "mappings": {
                "azure-na": {
                    "destinations": [
                        {
                            "destination": "new_azure_destination1",
                            "overwrite": True,
                            "restrict_version": False,
                        },
                        {
                            "destination": "new_azure_destination2",
                            "overwrite": False,
                            "restrict_version": False,
                        },
                    ]
                },
            },
            "name": "sample-product",
            "workflow": "stratosphere",
            "cloud": "azure",
        },
    ]

    command_tester.test(
        lambda: entry_point(MarketplacesVMPush),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--repo",
            json.dumps(policy),
            "--debug",
            "koji:https://fakekoji.com?vmi_build=ami_build,azure_build",
        ],
    )

    _check_collector_update_push_items(
        mock_collector_update_push_items, expected_ami_pi_count=2, expected_vhd_pi_count=2
    )


@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
def test_push_offline_starmap(
    mock_source: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
    fake_cloud_instance: mock.MagicMock,
    command_tester: CommandTester,
    ami_push_item: AmiPushItem,
    vhd_push_item: VHDPushItem,
) -> None:
    """Test a push success without connection to the Starmap Server using --repo mappings."""
    binfo = KojiBuildInfo(name="sample-product", version="7.0", release="20230101")
    ami_push_item = evolve(ami_push_item, build_info=binfo)
    vhd_push_item = evolve(vhd_push_item, build_info=binfo)
    mock_source.get.return_value.__enter__.return_value = [ami_push_item, vhd_push_item]

    policy = [
        {
            "mappings": {
                "azure-na": {
                    "destinations": [
                        {
                            "destination": "new_azure_destination1",
                            "overwrite": True,
                            "restrict_version": False,
                        },
                        {
                            "destination": "new_azure_destination2",
                            "overwrite": False,
                            "restrict_version": False,
                        },
                    ]
                },
            },
            "name": "sample-product",
            "workflow": "stratosphere",
            "cloud": "azure",
        },
        {
            "mappings": {
                "aws-na": {
                    "destinations": [
                        {
                            "destination": "new_aws_na_destination",
                            "overwrite": False,
                            "restrict_version": False,
                        }
                    ]
                },
                "aws-emea": {
                    "destinations": [
                        {
                            "destination": "new_aws_emea_destination",
                            "overwrite": True,
                            "restrict_version": False,
                        }
                    ]
                },
            },
            "name": "sample-product",
            "workflow": "stratosphere",
            "cloud": "aws",
        },
    ]

    command_tester.test(
        lambda: entry_point(MarketplacesVMPush),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--repo",
            json.dumps(policy),
            "--offline",
            "--debug",
            "koji:https://fakekoji.com?vmi_build=ami_build,azure_build",
        ],
    )

    _check_collector_update_push_items(
        mock_collector_update_push_items, expected_ami_pi_count=2, expected_vhd_pi_count=2
    )


@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
def test_push_offline_no_repo(
    mock_source: mock.MagicMock,
    fake_cloud_instance: mock.MagicMock,
    command_tester: CommandTester,
    ami_push_item: AmiPushItem,
    vhd_push_item: VHDPushItem,
    capsys: CaptureFixture,
) -> None:
    """Test whether tooling shows error when trying to use the StArMap offline without --repo."""
    binfo = KojiBuildInfo(name="sample-product", version="7.0", release="20230101")
    ami_push_item = evolve(ami_push_item, build_info=binfo)
    vhd_push_item = evolve(vhd_push_item, build_info=binfo)
    mock_source.get.return_value.__enter__.return_value = [ami_push_item, vhd_push_item]

    command_tester.test(
        lambda: entry_point(MarketplacesVMPush),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--offline",
            "--debug",
            "koji:https://fakekoji.com?vmi_build=ami_build,azure_build",
        ],
    )

    _, err = capsys.readouterr()
    assert "Cannot use \"--offline\" without defining \"--repo\" mappings." in err


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
@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
def test_empty_value_to_collect(
    mock_source: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
    mock_push: mock.MagicMock,
    mock_upload: mock.MagicMock,
    mock_prepublish: mock.MagicMock,
    fake_starmap: mock.MagicMock,
    ami_push_item: AmiPushItem,
    command_tester: CommandTester,
    starmap_query_aws: QueryResponseEntity,
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

    _check_collector_update_push_items(
        mock_collector_update_push_items, expected_ami_pi_count=1, expected_vhd_pi_count=0
    )


@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush._push_pre_publish")
@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush._push_upload")
@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush._push_publish")
@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
def test_empty_items_not_allowed(
    mock_source: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
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

    _check_collector_update_push_items(
        mock_collector_update_push_items, expected_ami_pi_count=0, expected_vhd_pi_count=0
    )


@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush._push_pre_publish")
@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush._push_upload")
@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush._push_publish")
@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
def test_empty_items_allowed(
    mock_source: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
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

    _check_collector_update_push_items(
        mock_collector_update_push_items, expected_ami_pi_count=0, expected_vhd_pi_count=0
    )


@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
def test_push_item_rhcos_gov(
    mock_source: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
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

    _check_collector_update_push_items(
        mock_collector_update_push_items, expected_ami_pi_count=2, expected_vhd_pi_count=3
    )


@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.cloud_instance")
@mock.patch("pushcollector._impl.proxy.CollectorProxy.update_push_items")
@mock.patch("pubtools._marketplacesvm.tasks.push.command.Source")
@mock.patch("pubtools._marketplacesvm.tasks.push.MarketplacesVMPush.starmap")
def test_do_push_collected_push_items(
    mock_starmap: mock.MagicMock,
    mock_source: mock.MagicMock,
    mock_collector_update_push_items: mock.MagicMock,
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
            push_item = evolve(push_item, image_id=self.amis.pop(0))
            return push_item, True

        def _pre_publish(self, push_item, **kwargs):
            return push_item, kwargs

        def _publish(self, push_item, nochannel, overwrite, **kwargs):
            # This log will allow us to identify whether the image_id is the expected
            self.log.debug(f"Pushing {push_item.name} with image: {push_item.image_id}")
            return push_item, nochannel

    mock_cloud_instance.return_value = FakeAWSProvider()

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
                            "overwrite": False,
                            "restrict_version": True,
                            "restrict_major": 3,
                            "restrict_minor": 1,
                            "meta": {"description": "NA description"},
                        },
                    ]
                },
                "aws-emea": {
                    "destinations": [
                        {
                            "destination": "EMEA-DESTINATION",
                            "overwrite": False,
                            "restrict_version": True,
                            "restrict_major": 3,
                            "restrict_minor": 1,
                            "meta": {"description": "EMEA description"},
                        },
                    ]
                },
            },
        }
    )
    mock_starmap.query_image_by_name.return_value = QueryResponseContainer([qre])
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
    assert mock_cloud_instance.call_count == 6

    exp_ami_release = AmiRelease(
        product='sample-product',
        date=datetime(2025, 4, 2, 17, 56, 59),
        arch='x86_64',
        respin=1,
        version='7.0',
    )

    exp_na_pi = AmiPushItem(
        **dict(
            name='ami_pushitem',
            state=State.PUSHED,
            build_info=KojiBuildInfo(name='test-build', version='7.0', release='20230101'),
            release=exp_ami_release,
            dest=['NA-DESTINATION'],
            description='NA description',
            image_id='fake-ami-id-for-na',
        )
    )
    exp_emea_pi = AmiPushItem(
        **dict(
            name='ami_pushitem',
            state=State.PUSHED,
            build_info=KojiBuildInfo(name='test-build', version='7.0', release='20230101'),
            release=exp_ami_release,
            dest=['EMEA-DESTINATION'],
            description='EMEA description',
            image_id='fake-ami-id-for-emea',
        )
    )

    mock_collector_update_push_items.assert_called_once_with([exp_na_pi, exp_emea_pi])
