# SPDX-License-Identifier: GPL-3.0-or-later
from copy import copy
from unittest.mock import MagicMock, patch

import pytest
from attrs import evolve
from pushsource import KojiBuildInfo, VHDPushItem, VMIRelease

from pubtools._marketplacesvm.cloud_providers import AzureCredentials, AzureProvider, get_provider
from pubtools._marketplacesvm.cloud_providers.base import UPLOAD_CONTAINER_NAME


@pytest.fixture
def fake_credentials() -> AzureCredentials:
    params = {
        "cloud_name": "test-na",
        "AZURE_PUBLISHER_NAME": "publisher",
        "AZURE_TENANT_ID": "tenant-id",
        "AZURE_CLIENT_ID": "client-id",
        "AZURE_API_SECRET": "api-secret",
        "AZURE_STORAGE_CONNECTION_STRING": "DefaultEndpointsProtocol=https;AccountName=foo;AccountKey=bar;EndpointSuffix=suffix",  # noqa: E501
    }
    return AzureCredentials(**params)


@pytest.fixture
def fake_azure_provider(
    fake_credentials: AzureCredentials, monkeypatch: pytest.MonkeyPatch
) -> AzureProvider:
    provider = AzureProvider(fake_credentials)
    monkeypatch.setattr(provider, 'upload_svc', MagicMock())
    monkeypatch.setattr(provider, 'publish_svc', MagicMock())
    return provider


@pytest.fixture
def vmi_release() -> VMIRelease:
    params = {
        "product": "sample_product",
        "base_product": "base_product",
        "date": "2023-01-30",
        "arch": "x86_64",
        "respin": 0,
        "version": "1.0",
        "base_version": "1.1",
        "type": "GA",
    }
    return VMIRelease(**params)


@pytest.fixture
def azure_push_item(vmi_release: VMIRelease) -> VHDPushItem:
    params = {
        "name": "sample_product-1.0-0-x86_64.vhd",
        "description": "foo",
        "src": "/foo/bar/image.vhd",
        "dest": ["product-name/plan-name"],
        "build": "sample_product-1.0-0-x86_64",
        "generation": "V2",
        "sku_id": "plan-name",
        "support_legacy": True,
        "disk_version": "1.2.3",
        "sas_uri": "https://example.blob.core.windows.net/test/image.vhd?sp=r&st=2023-01-30T17:50:07Z&se=2023-01-31T01:50:07Z&spr=https&sv=2021-06-08&sr=b&sig=foobar",  # noqa: E501
        "release": vmi_release,
    }
    return VHDPushItem(**params)


@pytest.mark.parametrize("marketplace_account", ["azure-na", "azure-emea"])
def test_get_provider(marketplace_account: str, fake_credentials: AzureCredentials) -> None:
    conn_str = (
        "DefaultEndpointsProtocol=https;"
        "AccountName=test;AccountKey=test;"
        "EndpointSuffix=core.windows.net"
    )
    creds = fake_credentials.credentials
    creds.update({"AZURE_STORAGE_CONNECTION_STRING": conn_str})
    auth_data = {"marketplace_account": marketplace_account, "auth": creds}
    provider = get_provider(auth_data)  # type: ignore
    assert isinstance(provider, AzureProvider)


def test_name_from_push_item(
    azure_push_item: VHDPushItem, fake_azure_provider: AzureProvider
) -> None:
    expected_name = "base_product-1.1-sample_product-1.0_V2_GA-20230130-x86_64-0"

    res = fake_azure_provider._name_from_push_item(azure_push_item)
    assert res == expected_name


@patch("pubtools._marketplacesvm.cloud_providers.ms_azure.AzureUploadMetadata")
def test_upload(
    mock_metadata: MagicMock, azure_push_item: VHDPushItem, fake_azure_provider: AzureProvider
) -> None:
    binfo = azure_push_item.build_info
    tags = {
        "arch": azure_push_item.release.arch,
        "buildid": azure_push_item.build,
        "name": azure_push_item.build_info.name,
        "nvra": f"{binfo.name}-{binfo.version}-{binfo.release}.{azure_push_item.release.arch}",
        "release": azure_push_item.build_info.release,
        "version": azure_push_item.build_info.version,
    }
    metadata = {
        "arch": azure_push_item.release.arch,
        "container": UPLOAD_CONTAINER_NAME,
        "description": azure_push_item.description,
        "image_name": fake_azure_provider._name_from_push_item(azure_push_item),
        "image_path": azure_push_item.src,
        "tags": tags,
    }
    meta_obj = MagicMock(**metadata)
    mock_metadata.return_value = meta_obj
    fake_azure_provider.upload_svc.get_blob_sas_uri.return_value = "FAKE_SAS_URI"

    fake_azure_provider.upload(azure_push_item)

    mock_metadata.assert_called_once_with(**metadata)
    fake_azure_provider.upload_svc.publish.assert_called_once_with(meta_obj)
    fake_azure_provider.publish_svc.publish.assert_not_called()


@patch("pubtools._marketplacesvm.cloud_providers.ms_azure.AzurePublishMetadata")
def test_publish(
    mock_metadata: MagicMock,
    azure_push_item: VHDPushItem,
    fake_azure_provider: AzureProvider,
) -> None:
    azure_push_item = evolve(azure_push_item, disk_version=None)
    mock_generate_dv = MagicMock()
    mock_generate_dv.return_value = "7.0.202301010000"
    metadata = {
        "sku_id": azure_push_item.sku_id,
        "generation": azure_push_item.generation or "V2",
        "support_legacy": azure_push_item.support_legacy or False,
        "recommended_sizes": azure_push_item.recommended_sizes or [],
        "legacy_sku_id": azure_push_item.legacy_sku_id,
        "image_path": azure_push_item.sas_uri,
        "architecture": azure_push_item.release.arch,
        "destination": azure_push_item.dest[0],
        "keepdraft": False,
        "overwrite": False,
    }
    meta_obj = MagicMock(**metadata)
    mock_metadata.return_value = meta_obj
    expected_metadata = copy(metadata)
    expected_metadata.update({"disk_version": "7.0.202301010000"})

    with patch.object(fake_azure_provider, '_generate_disk_version', mock_generate_dv):
        fake_azure_provider.publish(azure_push_item, nochannel=False, overwrite=False)

    mock_metadata.assert_called_once_with(**expected_metadata)
    fake_azure_provider.publish_svc.publish.assert_called_once_with(meta_obj)
    fake_azure_provider.upload_svc.publish.assert_not_called()


@patch("pubtools._marketplacesvm.cloud_providers.ms_azure.datetime")
def test_generate_disk_version(
    mock_date: MagicMock, azure_push_item: VHDPushItem, fake_azure_provider: AzureProvider
) -> None:
    mock_strftime = MagicMock()
    mock_strftime.strftime.return_value = "202301010000"
    mock_date.now.return_value = mock_strftime
    b_info = KojiBuildInfo(name=azure_push_item.name, version="7.0", release="0")
    push_item = evolve(azure_push_item, build_info=b_info)

    res = fake_azure_provider._generate_disk_version(push_item)

    assert res == "7.0.202301010000"
