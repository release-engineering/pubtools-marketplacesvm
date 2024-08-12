# SPDX-License-Identifier: GPL-3.0-or-later
import os
from copy import copy
from unittest.mock import MagicMock, patch

import pytest
from attrs import evolve
from cloudpub.models.ms_azure import Product
from pushsource import KojiBuildInfo, VHDPushItem, VMIRelease

from pubtools._marketplacesvm.cloud_providers import AzureCredentials, AzureProvider, get_provider
from pubtools._marketplacesvm.cloud_providers.base import UPLOAD_CONTAINER_NAME
from pubtools._marketplacesvm.cloud_providers.ms_azure import AzureDestinationBorg


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
        "build_info": KojiBuildInfo(
            name="sample-product", version="1.0.1", release="20230101", id=1234
        ),
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
        "buildid": str(azure_push_item.build_info.id),
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


@patch("pubtools._marketplacesvm.cloud_providers.ms_azure.AzureUploadMetadata")
def test_rhcos_upload(
    mock_metadata: MagicMock, azure_push_item: VHDPushItem, fake_azure_provider: AzureProvider
) -> None:
    azure_push_item = evolve(azure_push_item, src="https://rhcos_data.windows.net")
    azure_push_item = evolve(azure_push_item, build='rhcos-x86_64-414.92.202405201754-0')
    binfo = azure_push_item.build_info

    tags = {
        "arch": azure_push_item.release.arch,
        "buildid": str(azure_push_item.build_info.id),
        "name": azure_push_item.build_info.name,
        "nvra": f"{binfo.name}-{'414.92.202405201754'}-{binfo.release}.{azure_push_item.release.arch}",  # noqa: E501
        "release": azure_push_item.build_info.release,
        "version": "414.92.202405201754",
    }
    metadata = {
        "arch": azure_push_item.release.arch,
        "container": UPLOAD_CONTAINER_NAME,
        "description": azure_push_item.description,
        "image_name": fake_azure_provider._name_from_push_item(azure_push_item),
        "image_path": azure_push_item.src,
        "tags": tags,
    }

    fake_azure_provider.upload_svc.get_blob_sas_uri.return_value = "FAKE_SAS_URI"
    fake_azure_provider.upload(azure_push_item)
    mock_metadata.assert_called_once_with(**metadata)

    fake_azure_provider.upload_svc.publish.assert_called_once()
    fake_azure_provider.publish_svc.publish.assert_not_called()


@patch("pubtools._marketplacesvm.cloud_providers.ms_azure.AzureUploadMetadata")
def test_upload_custom_tags(
    mock_metadata: MagicMock, azure_push_item: VHDPushItem, fake_azure_provider: AzureProvider
) -> None:
    binfo = azure_push_item.build_info
    custom_tags = {"custom_key": "custom_value"}
    tags = {
        "arch": azure_push_item.release.arch,
        "buildid": str(azure_push_item.build_info.id),
        "name": azure_push_item.build_info.name,
        "nvra": f"{binfo.name}-{binfo.version}-{binfo.release}.{azure_push_item.release.arch}",
        "release": azure_push_item.build_info.release,
        "version": azure_push_item.build_info.version,
        **custom_tags,
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

    fake_azure_provider.upload(azure_push_item, custom_tags=custom_tags)

    mock_metadata.assert_called_once_with(**metadata)
    fake_azure_provider.upload_svc.publish.assert_called_once_with(meta_obj)
    fake_azure_provider.publish_svc.publish.assert_not_called()


def test_pre_publish(azure_push_item: VHDPushItem, fake_azure_provider: AzureProvider):
    fake_publish = MagicMock()
    fake_publish.return_value = [azure_push_item, {"param": True}]

    with patch.object(fake_azure_provider, "_publish", fake_publish):
        pi, res = fake_azure_provider._pre_publish(azure_push_item, param=True)

    fake_publish.assert_called_once_with(push_item=azure_push_item, nochannel=True, param=True)
    assert (pi, res) == (azure_push_item, {"param": True})


@patch("pubtools._marketplacesvm.cloud_providers.ms_azure.AzurePublishMetadata")
def test_publish(
    mock_metadata: MagicMock,
    azure_push_item: VHDPushItem,
    fake_azure_provider: AzureProvider,
    monkeypatch: pytest.MonkeyPatch,
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
    mock_ensure_offer_writable = MagicMock()

    monkeypatch.setattr(fake_azure_provider, '_generate_disk_version', mock_generate_dv)
    monkeypatch.setattr(fake_azure_provider, 'ensure_offer_is_writable', mock_ensure_offer_writable)

    fake_azure_provider.publish(azure_push_item, nochannel=False, overwrite=False)

    mock_metadata.assert_called_once_with(**expected_metadata)
    fake_azure_provider.publish_svc.publish.assert_called_once_with(meta_obj)
    fake_azure_provider.upload_svc.publish.assert_not_called()
    mock_ensure_offer_writable.assert_called_once()


@patch("pubtools._marketplacesvm.cloud_providers.ms_azure.AzurePublishMetadata")
def test_publish_allow_draft(
    mock_metadata: MagicMock,
    fake_credentials: AzureCredentials,
    azure_push_item: VHDPushItem,
    monkeypatch: pytest.MonkeyPatch,
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
    mock_metadata.return_value = MagicMock(**metadata)
    mock_ensure_offer_writable = MagicMock()

    # Set environment to allow draft push and create a provider with the patched data
    monkeypatch.setenv("AZURE_ALLOW_DRAFT_PUSH", "true")
    provider = AzureProvider(fake_credentials)
    monkeypatch.setattr(provider, 'upload_svc', MagicMock())
    monkeypatch.setattr(provider, 'publish_svc', MagicMock())
    monkeypatch.setattr(provider, '_generate_disk_version', mock_generate_dv)
    monkeypatch.setattr(provider, 'ensure_offer_is_writable', mock_ensure_offer_writable)

    # Test
    provider.publish(azure_push_item, nochannel=False, overwrite=False)

    # Ensure the draft lock was not called
    mock_ensure_offer_writable.assert_not_called()


@patch("pubtools._marketplacesvm.cloud_providers.ms_azure.AzurePublishMetadata")
def test_publish_fails_on_draft_state(
    mock_metadata: MagicMock,
    azure_push_item: VHDPushItem,
    fake_azure_provider: AzureProvider,
) -> None:
    fake_product = Product.from_json(
        {
            "$schema": "https://product-ingestion.azureedge.net/schema/resource-tree/2022-03-01-preview2",  # noqa: E501
            "root": "product/product/ffffffff-ffff-ffff-ffff-ffffffffffff",
            "target": {"targetType": "draft"},  # this should prevent the offer to be published
            "resources": [],
        }
    )
    fake_azure_provider.publish_svc.get_product_by_name.return_value = fake_product
    keep_draft = True
    offer_name = azure_push_item.dest[0].split("/")[0]
    expected_err = f"Can't update the offer {offer_name} as it's already being changed."

    with pytest.raises(RuntimeError, match=expected_err):
        fake_azure_provider.publish(azure_push_item, nochannel=keep_draft, overwrite=False)

    mock_metadata.assert_not_called()
    fake_azure_provider.publish_svc.publish.assert_not_called()
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


@patch("pubtools._marketplacesvm.cloud_providers.ms_azure.datetime")
def test_generate_disk_version_xyz(
    mock_date: MagicMock, azure_push_item: VHDPushItem, fake_azure_provider: AzureProvider
) -> None:
    mock_strftime = MagicMock()
    mock_strftime.strftime.return_value = "202301010000"
    mock_date.now.return_value = mock_strftime
    b_info = KojiBuildInfo(name=azure_push_item.name, version="7.0.15", release="0")
    push_item = evolve(azure_push_item, build_info=b_info)

    res = fake_azure_provider._generate_disk_version(push_item)

    assert res == "7.0.202301010000"

    # Make sure we pass Pushsource regex for versioning
    evolve(push_item, disk_version=res)


def test_borg() -> None:
    a = AzureDestinationBorg()
    b = AzureDestinationBorg()

    a.destinations.add("test")

    assert a != b
    assert a.destinations == b.destinations
    assert "test" in b.destinations


@patch("pubtools._marketplacesvm.cloud_providers.ms_azure.datetime")
def test_post_publish(
    mock_datetime: MagicMock,
    azure_push_item: VHDPushItem,
    fake_azure_provider: AzureProvider,
) -> None:
    mock_blob = MagicMock()
    mock_blob.get_blob_tags.return_value = {}
    mock_datetime.now.return_value.strftime.return_value = "20230623"

    fake_azure_provider.upload_svc.get_object_by_name.return_value = mock_blob
    name = os.path.basename(azure_push_item.src).rstrip(".xz")
    container = UPLOAD_CONTAINER_NAME

    fake_azure_provider._post_publish(azure_push_item, "publish_result", False)

    fake_azure_provider.upload_svc.get_object_by_name.assert_called_once_with(container, name)

    mock_blob.get_blob_tags.assert_called_once()
    mock_datetime.now.return_value.strftime.assert_called_once_with("%Y%m%d%H::%M::%S")

    test_dict = {"release_date": "20230623"}
    mock_blob.set_blob_tags.assert_called_once_with(test_dict)


@patch("pubtools._marketplacesvm.cloud_providers.ms_azure.datetime")
def test_post_publish_nochannel(
    mock_datetime: MagicMock,
    azure_push_item: VHDPushItem,
    fake_azure_provider: AzureProvider,
) -> None:
    mock_blob = MagicMock()
    mock_blob.get_blob_tags.return_value = {}
    mock_datetime.now.return_value.strftime.return_value = "20230623"

    fake_azure_provider.upload_svc.get_object_by_name.return_value = mock_blob

    fake_azure_provider._post_publish(azure_push_item, "publish_result", True)

    fake_azure_provider.upload_svc.get_object_by_name.assert_not_called()

    mock_blob.get_blob_tags.assert_not_called()
    mock_datetime.now.return_value.strftime.assert_not_called()
    mock_blob.set_blob_tags.assert_not_called()
