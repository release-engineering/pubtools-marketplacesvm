# SPDX-License-Identifier: GPL-3.0-or-later
from datetime import datetime
from typing import Any, Dict, Union
from unittest.mock import MagicMock, patch

import pytest
from attrs import evolve
from cloudpub.models.aws import VersionMapping as AWSVersionMapping
from pushsource import (
    AmiBillingCodes,
    AmiPushItem,
    AmiRelease,
    AmiSecurityGroup,
    BootMode,
    KojiBuildInfo,
)

from pubtools._marketplacesvm.cloud_providers import AWSCredentials, AWSProvider, get_provider
from pubtools._marketplacesvm.cloud_providers.aws import name_from_push_item
from pubtools._marketplacesvm.cloud_providers.base import UPLOAD_CONTAINER_NAME


@pytest.fixture
def fake_credentials() -> AWSCredentials:
    params = {
        "cloud_name": "test-na",
        "AWS_IMAGE_ACCESS_KEY": "fake-access-key",
        "AWS_IMAGE_SECRET_ACCESS": "fake-secrets",
        "AWS_MARKETPLACE_ACCESS_KEY": "fake-access-key",
        "AWS_MARKETPLACE_SECRET_ACCESS": "fake-secrets",
        "AWS_ACCESS_ROLE_ARN": "secret-role",
        "AWS_GROUPS": ["2134", "124523"],
        "AWS_SNAPSHOT_ACCOUNTS": ["23532", "32532234"],
        "AWS_REGION": "us-east-1",
    }
    return AWSCredentials(**params)  # type: ignore


@pytest.fixture
@patch("pubtools._marketplacesvm.cloud_providers.aws.AWSPublishService")
@patch("pubtools._marketplacesvm.cloud_providers.aws.AWSUploadService")
def fake_aws_provider(
    mock_upload: MagicMock,
    mock_publish: MagicMock,
    fake_credentials: AWSCredentials,
    monkeypatch: pytest.MonkeyPatch,
):
    provider = AWSProvider(fake_credentials)
    monkeypatch.setattr(provider, 'upload_svc_partial', mock_upload)
    monkeypatch.setattr(provider, 'publish_svc', mock_publish)
    return provider


@pytest.fixture
def ami_release() -> AmiRelease:
    params = {
        "product": "sample_product",
        "base_product": "base_product",
        "date": "2023-01-30",
        "arch": "x86_64",
        "respin": 0,
        "version": "1.0.1",
        "base_version": "1.1.1",
        "type": "GA",
    }
    return AmiRelease(**params)


@pytest.fixture
def security_group() -> AmiSecurityGroup:
    params = {
        "from_port": 22,
        "ip_protocol": "tcp",
        "ip_ranges": ["22.22.22.22", "33.33.33.33"],
        "to_port": 22,
    }
    return AmiSecurityGroup._from_data(params)


@pytest.fixture
def aws_push_item(ami_release: AmiRelease, security_group: AmiSecurityGroup) -> AmiPushItem:
    params = {
        "name": "sample_product-1.0.1-1-x86_64.raw",
        "description": "foo",
        "src": "/foo/bar/image.raw",
        "dest": ["product-uuid"],
        "build": "sample_product-1.0.1-1-x86_64",
        "build_info": KojiBuildInfo(
            name="test-build", version="1.0.1", release="20230101", id=1234
        ),
        "virtualization": "virt",
        "volume": "gp2",
        "release": ami_release,
        "scanning_port": 22,
        "user_name": "fake-user",
        "release_notes": "https://access.redhat.com/{major_version}/{major_minor}",
        "usage_instructions": "Example. {major_version} - {major_minor}",
        "recommended_instance_type": "m5.large",
        "marketplace_entity_type": "FakeProduct",
        "security_groups": [security_group],
    }
    return AmiPushItem(**params)


@pytest.fixture
def aws_product_versions() -> Dict[str, Any]:
    product_versions = {
        "Fake-Version": {
            "delivery_options": [
                {"id": "fake-id1", "visibility": "Restricted"},
                {"id": "fake-id2", "visibility": "Public"},
            ],
            "created_date": "2023-02-24T12:41:25.503Z",
        },
        "Fake-Version2": {
            "delivery_options": [
                {"id": "fake-id1", "visibility": "Limited"},
                {"id": "fake-id2", "visibility": "Restricted"},
            ],
            "created_date": "2023-01-24T12:41:25.503Z",
        },
    }
    return product_versions


class FakeImageResp:
    id: str = "fake-image-id"


class FakeImageTag:
    resource_id: str = "ami-08db234c2221633a0"
    key: str = "release_date"
    value: str = "2023062113::16::33"


@pytest.mark.parametrize("marketplace_account", ["aws-na", "aws-emea"])
@patch("pubtools._marketplacesvm.cloud_providers.aws.AWSPublishService")
@patch("pubtools._marketplacesvm.cloud_providers.aws.AWSUploadService")
def test_get_provider(
    mock_upload: MagicMock,
    mock_publish: MagicMock,
    marketplace_account: str,
    fake_credentials: AWSCredentials,
) -> None:
    creds = fake_credentials.credentials
    creds.update({"AWS_IMAGE_ACCESS_KEY": "updated-access-key"})
    auth_data = {"marketplace_account": marketplace_account, "auth": creds}
    provider = get_provider(auth_data)  # type: ignore
    assert isinstance(provider, AWSProvider)


def test_name_from_push_item(aws_push_item: AmiPushItem, fake_aws_provider: AWSProvider):
    expected_name = "base_product-1.1-sample_product-1.0_VIRT_GA-20230130-x86_64-0"
    res = name_from_push_item(aws_push_item)
    assert res == expected_name


def test_name_from_push_item_community(aws_push_item: AmiPushItem, fake_aws_provider: AWSProvider):
    bc_dict = {"codes": ["foo", "bar"], "name": "fake-billing-code"}
    bc = AmiBillingCodes._from_data(bc_dict)
    pi = evolve(aws_push_item, billing_codes=bc)
    expected_name = "base_product-1.1-sample_product-1.0_VIRT_GA-20230130-x86_64-0-fake-billing-code-GP2"  # noqa: E501
    res = name_from_push_item(pi)
    assert res == expected_name


def test_get_security_items(aws_push_item: AmiPushItem, fake_aws_provider: AWSProvider):
    res = fake_aws_provider._get_security_items(aws_push_item)
    assert [AmiSecurityGroup._from_data(x) for x in res] == aws_push_item.security_groups


def test_format_version_info(aws_push_item: AmiPushItem, fake_aws_provider: AWSProvider):
    expected_output = "https://access.redhat.com/1/1.0"
    res = fake_aws_provider._format_version_info(
        aws_push_item.release_notes, aws_push_item.release.version
    )
    assert res == expected_output


@patch("pubtools._marketplacesvm.cloud_providers.aws.AWSUploadMetadata")
def test_upload(
    mock_metadata: MagicMock, aws_push_item: AmiPushItem, fake_aws_provider: AWSProvider
):
    created_name = name_from_push_item(aws_push_item)
    binfo = aws_push_item.build_info

    tags = {
        "arch": aws_push_item.release.arch,
        "buildid": str(aws_push_item.build_info.id),
        "name": aws_push_item.build_info.name,
        "nvra": f"{binfo.name}-{binfo.version}-{binfo.release}.{aws_push_item.release.arch}",
        "release": aws_push_item.build_info.release,
        "version": aws_push_item.build_info.version,
    }
    metadata = {
        "billing_products": [],
        "image_path": aws_push_item.src,
        "image_name": created_name,
        "snapshot_name": created_name,
        "container": UPLOAD_CONTAINER_NAME,
        "description": aws_push_item.description,
        "arch": aws_push_item.release.arch,
        "virt_type": aws_push_item.virtualization,
        "root_device_name": aws_push_item.root_device,
        "volume_type": aws_push_item.volume,
        "accounts": fake_aws_provider.aws_groups,
        "snapshot_account_ids": fake_aws_provider.aws_snapshot_accounts,
        "sriov_net_support": aws_push_item.sriov_net_support,
        "ena_support": aws_push_item.ena_support,
        "tags": tags,
    }
    meta_obj = MagicMock(**metadata)
    mock_metadata.return_value = meta_obj

    fake_aws_provider.upload_svc_partial.return_value.publish.return_value = FakeImageResp()  # type: ignore [attr-defined] # noqa: E501

    fake_aws_provider.upload(aws_push_item)

    mock_metadata.assert_called_once_with(**metadata)
    fake_aws_provider.upload_svc_partial.return_value.publish.assert_called_once_with(meta_obj)  # type: ignore [attr-defined] # noqa: E501
    fake_aws_provider.publish_svc.publish.assert_not_called()


@pytest.mark.parametrize("region", ["us-gov-west-1", "eu-north-1", "cn-north-1"])
@patch("pubtools._marketplacesvm.cloud_providers.aws.AWSUploadMetadata")
def test_upload_different_region(
    mock_metadata: MagicMock,
    region: str,
    aws_push_item: AmiPushItem,
    fake_aws_provider: AWSProvider,
):
    fake_upload_response = MagicMock()
    fake_upload_response.id = "fake-ami-id"

    binfo = aws_push_item.build_info
    bc_dict = {"codes": ["foo", "bar"], "name": "fake-billing-code"}
    bc = AmiBillingCodes._from_data(bc_dict)
    aws_push_item = evolve(aws_push_item, region=region, billing_codes=bc)
    created_name = name_from_push_item(aws_push_item)

    tags = {
        "arch": aws_push_item.release.arch,
        "buildid": str(aws_push_item.build_info.id),
        "name": aws_push_item.build_info.name,
        "nvra": f"{binfo.name}-{binfo.version}-{binfo.release}.{aws_push_item.release.arch}",
        "release": aws_push_item.build_info.release,
        "version": aws_push_item.build_info.version,
    }
    metadata = {
        "billing_products": bc.codes,
        "image_path": aws_push_item.src,
        "image_name": created_name,
        "snapshot_name": created_name,
        "container": UPLOAD_CONTAINER_NAME,
        "description": aws_push_item.description,
        "arch": aws_push_item.release.arch,
        "virt_type": aws_push_item.virtualization,
        "root_device_name": aws_push_item.root_device,
        "volume_type": aws_push_item.volume,
        "accounts": fake_aws_provider.aws_groups,
        "snapshot_account_ids": fake_aws_provider.aws_snapshot_accounts,
        "sriov_net_support": aws_push_item.sriov_net_support,
        "ena_support": aws_push_item.ena_support,
        "tags": tags,
    }
    meta_obj = MagicMock(**metadata)
    mock_metadata.return_value = meta_obj

    fake_aws_provider.upload_svc_partial.return_value.publish.return_value = FakeImageResp()  # type: ignore [attr-defined] # noqa: E501

    fake_aws_provider.upload(aws_push_item)

    mock_metadata.assert_called_once_with(**metadata)
    # The self.upload_svc_partial should have been called with a different region
    fake_aws_provider.upload_svc_partial.assert_called_once_with(region=region)  # type: ignore [attr-defined] # noqa: E501
    fake_aws_provider.upload_svc_partial.return_value.publish.assert_called_once_with(meta_obj)  # type: ignore [attr-defined] # noqa: E501
    fake_aws_provider.publish_svc.publish.assert_not_called()


@pytest.mark.parametrize("boot_mode_str", ["legacy", "uefi", "hybrid"])
@patch("pubtools._marketplacesvm.cloud_providers.aws.AWSUploadMetadata")
def test_upload_boot_mode(
    mock_metadata: MagicMock,
    boot_mode_str: str,
    aws_push_item: AmiPushItem,
    fake_aws_provider: AWSProvider,
):
    aws_push_item = evolve(aws_push_item, boot_mode=BootMode(boot_mode_str))
    created_name = name_from_push_item(aws_push_item)
    binfo = aws_push_item.build_info

    tags = {
        "arch": aws_push_item.release.arch,
        "buildid": str(aws_push_item.build_info.id),
        "name": aws_push_item.build_info.name,
        "nvra": f"{binfo.name}-{binfo.version}-{binfo.release}.{aws_push_item.release.arch}",
        "release": aws_push_item.build_info.release,
        "version": aws_push_item.build_info.version,
    }
    metadata = {
        "billing_products": [],
        "image_path": aws_push_item.src,
        "image_name": created_name,
        "snapshot_name": created_name,
        "container": UPLOAD_CONTAINER_NAME,
        "description": aws_push_item.description,
        "arch": aws_push_item.release.arch,
        "virt_type": aws_push_item.virtualization,
        "root_device_name": aws_push_item.root_device,
        "volume_type": aws_push_item.volume,
        "accounts": fake_aws_provider.aws_groups,
        "snapshot_account_ids": fake_aws_provider.aws_snapshot_accounts,
        "sriov_net_support": aws_push_item.sriov_net_support,
        "ena_support": aws_push_item.ena_support,
        "boot_mode": boot_mode_str,
        "tags": tags,
    }
    meta_obj = MagicMock(**metadata)
    mock_metadata.return_value = meta_obj

    fake_aws_provider.upload_svc_partial.return_value.publish.return_value = FakeImageResp()  # type: ignore [attr-defined] # noqa: E501

    fake_aws_provider.upload(aws_push_item)

    mock_metadata.assert_called_once_with(**metadata)
    fake_aws_provider.upload_svc_partial.return_value.publish.assert_called_once_with(meta_obj)  # type: ignore [attr-defined] # noqa: E501
    fake_aws_provider.publish_svc.publish.assert_not_called()


@patch("pubtools._marketplacesvm.cloud_providers.aws.AWSUploadMetadata")
def test_upload_billing_codes(
    mock_metadata: MagicMock,
    aws_push_item: AmiPushItem,
    fake_aws_provider: AWSProvider,
):
    bc_dict = {"codes": ["foo", "bar"], "name": "fake-billing-code"}
    bc = AmiBillingCodes._from_data(bc_dict)

    aws_push_item = evolve(aws_push_item, billing_codes=bc)
    created_name = name_from_push_item(aws_push_item)
    binfo = aws_push_item.build_info

    tags = {
        "arch": aws_push_item.release.arch,
        "buildid": str(aws_push_item.build_info.id),
        "name": aws_push_item.build_info.name,
        "nvra": f"{binfo.name}-{binfo.version}-{binfo.release}.{aws_push_item.release.arch}",
        "release": aws_push_item.build_info.release,
        "version": aws_push_item.build_info.version,
    }
    metadata = {
        "billing_products": bc.codes,
        "image_path": aws_push_item.src,
        "image_name": created_name,
        "snapshot_name": created_name,
        "container": UPLOAD_CONTAINER_NAME,
        "description": aws_push_item.description,
        "arch": aws_push_item.release.arch,
        "virt_type": aws_push_item.virtualization,
        "root_device_name": aws_push_item.root_device,
        "volume_type": aws_push_item.volume,
        "accounts": fake_aws_provider.aws_groups,
        "snapshot_account_ids": fake_aws_provider.aws_snapshot_accounts,
        "sriov_net_support": aws_push_item.sriov_net_support,
        "ena_support": aws_push_item.ena_support,
        "tags": tags,
    }
    meta_obj = MagicMock(**metadata)
    mock_metadata.return_value = meta_obj

    fake_aws_provider.upload_svc_partial.return_value.publish.return_value = FakeImageResp()  # type: ignore [attr-defined] # noqa: E501

    fake_aws_provider.upload(aws_push_item)

    mock_metadata.assert_called_once_with(**metadata)
    fake_aws_provider.upload_svc_partial.return_value.publish.assert_called_once_with(meta_obj)  # type: ignore [attr-defined] # noqa: E501
    fake_aws_provider.publish_svc.publish.assert_not_called()


@patch("pubtools._marketplacesvm.cloud_providers.aws.AWSUploadMetadata")
@patch("pubtools._marketplacesvm.cloud_providers.aws.AWSPublishService")
@patch("pubtools._marketplacesvm.cloud_providers.aws.AWSUploadService")
def test_upload_custom_s3(
    mock_upload: MagicMock,
    mock_publish: MagicMock,
    mock_metadata: MagicMock,
    aws_push_item: AmiPushItem,
    fake_credentials: AWSCredentials,
    monkeypatch: pytest.MonkeyPatch,
):
    bucket_name = "custom_s3_bucket"
    creds = evolve(fake_credentials, AWS_S3_BUCKET=bucket_name)  # type: ignore
    fake_aws_provider = AWSProvider(creds)
    monkeypatch.setattr(fake_aws_provider, 'upload_svc_partial', MagicMock())
    monkeypatch.setattr(fake_aws_provider, 'publish_svc', MagicMock())

    created_name = name_from_push_item(aws_push_item)
    binfo = aws_push_item.build_info

    tags = {
        "arch": aws_push_item.release.arch,
        "buildid": str(aws_push_item.build_info.id),
        "name": aws_push_item.build_info.name,
        "nvra": f"{binfo.name}-{binfo.version}-{binfo.release}.{aws_push_item.release.arch}",
        "release": aws_push_item.build_info.release,
        "version": aws_push_item.build_info.version,
    }
    metadata = {
        "billing_products": [],
        "image_path": aws_push_item.src,
        "image_name": created_name,
        "snapshot_name": created_name,
        "container": bucket_name,
        "description": aws_push_item.description,
        "arch": aws_push_item.release.arch,
        "virt_type": aws_push_item.virtualization,
        "root_device_name": aws_push_item.root_device,
        "volume_type": aws_push_item.volume,
        "accounts": fake_aws_provider.aws_groups,
        "snapshot_account_ids": fake_aws_provider.aws_snapshot_accounts,
        "sriov_net_support": aws_push_item.sriov_net_support,
        "ena_support": aws_push_item.ena_support,
        "tags": tags,
    }
    meta_obj = MagicMock(**metadata)
    mock_metadata.return_value = meta_obj

    fake_aws_provider.upload_svc_partial.return_value.publish.return_value = FakeImageResp()  # type: ignore [attr-defined] # noqa: E501

    fake_aws_provider.upload(aws_push_item)

    mock_metadata.assert_called_once_with(**metadata)
    fake_aws_provider.upload_svc_partial.return_value.publish.assert_called_once_with(meta_obj)  # type: ignore [attr-defined] # noqa: E501
    fake_aws_provider.publish_svc.publish.assert_not_called()


@patch("pubtools._marketplacesvm.cloud_providers.aws.AWSUploadMetadata")
def test_upload_custom_tags(
    mock_metadata: MagicMock,
    aws_push_item: AmiPushItem,
    fake_aws_provider: AWSProvider,
):
    created_name = name_from_push_item(aws_push_item)
    binfo = aws_push_item.build_info

    custom_tags = {"custom_key": "custom_value"}

    tags = {
        "arch": aws_push_item.release.arch,
        "buildid": str(aws_push_item.build_info.id),
        "name": aws_push_item.build_info.name,
        "nvra": f"{binfo.name}-{binfo.version}-{binfo.release}.{aws_push_item.release.arch}",
        "release": aws_push_item.build_info.release,
        "version": aws_push_item.build_info.version,
        **custom_tags,
    }
    metadata = {
        "billing_products": [],
        "image_path": aws_push_item.src,
        "image_name": created_name,
        "snapshot_name": created_name,
        "container": UPLOAD_CONTAINER_NAME,
        "description": aws_push_item.description,
        "arch": aws_push_item.release.arch,
        "virt_type": aws_push_item.virtualization,
        "root_device_name": aws_push_item.root_device,
        "volume_type": aws_push_item.volume,
        "accounts": fake_aws_provider.aws_groups,
        "snapshot_account_ids": fake_aws_provider.aws_snapshot_accounts,
        "sriov_net_support": aws_push_item.sriov_net_support,
        "ena_support": aws_push_item.ena_support,
        "tags": tags,
    }
    meta_obj = MagicMock(**metadata)
    mock_metadata.return_value = meta_obj

    fake_aws_provider.upload_svc_partial.return_value.publish.return_value = FakeImageResp()  # type: ignore [attr-defined] # noqa: E501

    fake_aws_provider.upload(aws_push_item, custom_tags=custom_tags)

    mock_metadata.assert_called_once_with(**metadata)
    fake_aws_provider.upload_svc_partial.return_value.publish.assert_called_once_with(meta_obj)  # type: ignore [attr-defined] # noqa: E501
    fake_aws_provider.publish_svc.publish.assert_not_called()


@pytest.mark.parametrize("new_base_product", ["test-base", None])
@patch("pubtools._marketplacesvm.cloud_providers.aws.AWSPublishMetadata")
def test_publish(
    mock_metadata: MagicMock,
    new_base_product: Union[str, None],
    aws_push_item: AmiPushItem,
    fake_aws_provider: AWSProvider,
):
    # update base_product so we can test both naming conventions
    release = aws_push_item.release
    updated_release = evolve(release, base_product=new_base_product)
    updated_aws_push_item = evolve(aws_push_item, release=updated_release)
    updated_aws_push_item, _ = fake_aws_provider._post_upload(
        updated_aws_push_item, FakeImageResp()
    )
    fake_aws_provider._post_upload(updated_aws_push_item, FakeImageResp())

    release = updated_aws_push_item.release
    release_date = release.date.strftime("%Y%m%d")
    respin = str(release.respin)

    version = {
        "VersionTitle": f"{updated_aws_push_item.release.version} {release_date}-{respin}",
        "ReleaseNotes": fake_aws_provider._format_version_info(
            aws_push_item.release_notes, aws_push_item.release.version
        ),
    }
    delivery_opt = [
        {
            "Details": {
                "AmiDeliveryOptionDetails": {
                    "AmiSource": {
                        "AmiId": updated_aws_push_item.image_id,
                        "AccessRoleArn": fake_aws_provider.aws_access_role_arn,
                        "UserName": updated_aws_push_item.user_name,
                        "OperatingSystemName": updated_aws_push_item.build_info.name.split("-")[
                            0
                        ].upper(),
                        "OperatingSystemVersion": updated_aws_push_item.release.version,
                        "ScanningPort": updated_aws_push_item.scanning_port,
                    },
                    "UsageInstructions": fake_aws_provider._format_version_info(
                        aws_push_item.usage_instructions, aws_push_item.release.version
                    ),
                    "RecommendedInstanceType": updated_aws_push_item.recommended_instance_type,
                    "SecurityGroups": fake_aws_provider._get_security_items(aws_push_item),
                }
            }
        }
    ]
    version_mapping = {"Version": version, "DeliveryOptions": delivery_opt}
    version_mapping = AWSVersionMapping.from_json(version_mapping)
    metadata = {
        "image_path": updated_aws_push_item.image_id,
        "architecture": updated_aws_push_item.release.arch,
        "destination": aws_push_item.dest[0],
        "keepdraft": False,
        "overwrite": False,
        "version_mapping": version_mapping,
        "marketplace_entity_type": updated_aws_push_item.marketplace_entity_type,
    }
    meta_obj = MagicMock(**metadata)
    mock_metadata.return_value = meta_obj

    fake_aws_provider.publish(updated_aws_push_item, nochannel=False, overwrite=False)

    mock_metadata.assert_called_once_with(**metadata)
    fake_aws_provider.publish_svc.publish.assert_called_once_with(meta_obj)
    fake_aws_provider.upload_svc_partial.upload.assert_not_called()  # type: ignore [attr-defined] # noqa: E501


@pytest.mark.parametrize("new_base_product", ["test-base", None])
@patch("pubtools._marketplacesvm.cloud_providers.aws.AWSPublishMetadata")
def test_publish_version_exists(
    mock_metadata: MagicMock,
    new_base_product: Union[str, None],
    aws_push_item: AmiPushItem,
    fake_aws_provider: AWSProvider,
    aws_product_versions: Dict[str, Any],
):
    # update base_product so we can test both naming conventions
    release = aws_push_item.release
    updated_release = evolve(release, base_product=new_base_product)
    updated_aws_push_item = evolve(aws_push_item, release=updated_release)
    updated_aws_push_item, _ = fake_aws_provider._post_upload(
        updated_aws_push_item, FakeImageResp()
    )
    fake_aws_provider._post_upload(updated_aws_push_item, FakeImageResp())

    release = updated_aws_push_item.release
    release_date = release.date.strftime("%Y%m%d")
    respin = str(release.respin)

    version_title = f"{updated_aws_push_item.release.version} {release_date}-{respin}"

    version = {
        "VersionTitle": version_title,
        "ReleaseNotes": fake_aws_provider._format_version_info(
            aws_push_item.release_notes, aws_push_item.release.version
        ),
    }
    delivery_opt = [
        {
            "Details": {
                "AmiDeliveryOptionDetails": {
                    "AmiSource": {
                        "AmiId": updated_aws_push_item.image_id,
                        "AccessRoleArn": fake_aws_provider.aws_access_role_arn,
                        "UserName": updated_aws_push_item.user_name,
                        "OperatingSystemName": updated_aws_push_item.build_info.name.split("-")[
                            0
                        ].upper(),
                        "OperatingSystemVersion": updated_aws_push_item.release.version,
                        "ScanningPort": updated_aws_push_item.scanning_port,
                    },
                    "UsageInstructions": fake_aws_provider._format_version_info(
                        aws_push_item.usage_instructions, aws_push_item.release.version
                    ),
                    "RecommendedInstanceType": updated_aws_push_item.recommended_instance_type,
                    "SecurityGroups": fake_aws_provider._get_security_items(aws_push_item),
                }
            }
        }
    ]
    version_mapping = {"Version": version, "DeliveryOptions": delivery_opt}
    version_mapping = AWSVersionMapping.from_json(version_mapping)
    metadata = {
        "image_path": updated_aws_push_item.image_id,
        "architecture": updated_aws_push_item.release.arch,
        "destination": aws_push_item.dest[0],
        "keepdraft": False,
        "overwrite": False,
        "version_mapping": version_mapping,
        "marketplace_entity_type": updated_aws_push_item.marketplace_entity_type,
    }
    meta_obj = MagicMock(**metadata)
    mock_metadata.return_value = meta_obj

    new_fake_version = {
        "delivery_options": [
            {"id": "fake-id1", "visibility": "Limited"},
            {"id": "fake-id2", "visibility": "Restricted"},
        ],
        "created_date": "2023-01-24T12:41:25.503Z",
    }

    aws_product_versions[version_title] = new_fake_version

    fake_aws_provider.publish_svc.get_product_versions.return_value = aws_product_versions

    fake_aws_provider.publish_svc.restrict_minor_versions.return_value = ["ami-1", "ami-2"]

    _, res = fake_aws_provider.publish(
        updated_aws_push_item, nochannel=False, overwrite=False, delete_restricted=True
    )

    assert res == {}

    mock_metadata.assert_not_called()
    fake_aws_provider.publish_svc.publish.assert_not_called()
    fake_aws_provider.upload_svc_partial.upload.assert_not_called()  # type: ignore [attr-defined] # noqa: E501

    called_args = fake_aws_provider.upload_svc_partial.return_value.delete.call_args_list  # type: ignore [attr-defined] # noqa: E501

    assert called_args[0][0][0].image_id == "ami-1"
    assert called_args[1][0][0].image_id == "ami-2"


@pytest.mark.parametrize("aws_fake_version", ["19.11.111", "19.11", "19.11.3333"])
def test_post_publish(
    aws_fake_version: str, aws_push_item: AmiPushItem, fake_aws_provider: AWSProvider
):
    release = aws_push_item.release
    updated_release = evolve(release, version=aws_fake_version)
    updated_aws_push_item = evolve(aws_push_item, release=updated_release)

    fake_aws_provider.image_id = "ami-97969874573"
    fake_image = FakeImageResp()
    fake_aws_provider.upload_svc_partial.return_value.get_image_by_id.return_value = fake_image  # type: ignore [attr-defined] # noqa: E501
    fake_aws_provider.upload_svc_partial.return_value.tag_image.return_value = FakeImageTag()  # type: ignore [attr-defined] # noqa: E501

    fake_aws_provider.publish_svc.restrict_minor_versions.return_value = ["ami-1", "ami-2"]

    fake_pi_return, fake_result_return = fake_aws_provider._post_publish(
        updated_aws_push_item, None, True
    )
    fake_aws_provider.publish_svc.restrict_minor_versions.assert_called_once_with(
        'product-uuid', 'FakeProduct', '19.11'
    )
    assert fake_pi_return == updated_aws_push_item
    assert fake_result_return is None

    release_date_tag = {"release_date": datetime.now().strftime("%Y%m%d%H::%M::%S")}

    fake_aws_provider.upload_svc_partial.return_value.get_image_by_id.assert_called_once_with(  # type: ignore [attr-defined] # noqa: E501
        "ami-97969874573"
    )
    fake_aws_provider.upload_svc_partial.return_value.tag_image.assert_called_once_with(  # type: ignore [attr-defined] # noqa: E501
        fake_image, release_date_tag
    )

    called_args = fake_aws_provider.upload_svc_partial.return_value.delete.call_args_list  # type: ignore [attr-defined] # noqa: E501

    assert called_args[0][0][0].image_id == "ami-1"
    assert called_args[1][0][0].image_id == "ami-2"
