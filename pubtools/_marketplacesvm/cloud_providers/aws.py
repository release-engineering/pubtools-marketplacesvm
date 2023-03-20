import logging
from typing import Any, Dict, List, Optional, Tuple

from attrs import asdict, evolve, field, frozen
from attrs.validators import deep_iterable, instance_of
from cloudimg.aws import AWSPublishingMetadata as AWSUploadMetadata
from cloudimg.aws import AWSService as AWSUploadService
from cloudpub.aws import AWSProductService as AWSPublishService
from cloudpub.aws import AWSVersionMetadata as AWSPublishMetadata
from cloudpub.models.aws import VersionMapping as AWSVersionMapping
from pushsource import AmiPushItem

from .base import UPLOAD_CONTAINER_NAME, CloudCredentials, CloudProvider, register_provider

LOG = logging.getLogger("pubtools.marketplacesvm")


@frozen
class AWSCredentials(CloudCredentials):
    """Represent the credentials for AWSProvider."""

    aws_image_access_key: str = field(alias="AWS_IMAGE_ACCESS_KEY", validator=instance_of(str))
    """AWs Image access key."""

    aws_image_secret_access: str = field(
        alias="AWS_IMAGE_SECRET_ACCESS", validator=instance_of(str)
    )
    """AWS Image secret access."""

    aws_marketplace_access_key: str = field(
        alias="AWS_MARKETPLACE_ACCESS_KEY", validator=instance_of(str)
    )
    """AWS Marketplace access key."""

    aws_marketplace_secret_access: str = field(
        alias="AWS_MARKETPLACE_SECRET_ACCESS", validator=instance_of(str)
    )
    """AWS Marketplace secret access."""

    aws_access_role_arn: str = field(alias="AWS_ACCESS_ROLE_ARN", validator=instance_of(str))
    """Access role arn for AWS Marketplace."""

    aws_groups: Optional[List[str]] = field(
        alias="AWS_GROUPS",
        validator=deep_iterable(
            member_validator=instance_of(str),
            iterable_validator=instance_of(list),
        ),
        factory=list,
    )
    """Groups to share image with. Defaults to empty list."""

    aws_snapshot_accounts: Optional[List[str]] = field(
        alias="AWS_SNAPSHOT_ACCOUNTS",
        validator=deep_iterable(
            member_validator=instance_of(str),
            iterable_validator=instance_of(list),
        ),
        factory=list,
    )
    """Snapshot accounts to share to. Defaults to empty list."""

    aws_region: Optional[str] = field(
        alias="AWS_REGION", validator=instance_of(str), default="us-east-1"
    )
    """AWS Region. Defaults to 'us-east-1'."""

    @property
    def credentials(self) -> Dict[str, str]:
        """Return the credentials as a dictionary."""
        return {k.upper(): v for k, v in asdict(self).items() if k != "cloud_name"}


class AWSProvider(CloudProvider[AmiPushItem, AWSCredentials]):
    """The AWS marketplace provider."""

    def __init__(self, credentials: AWSCredentials) -> None:
        """
        Create an instance of AWSProvider.

        Args:
            credentials (AWSCredentials)
                credentials to use the AWS Boto3.
        """
        self.aws_access_role_arn = credentials.aws_access_role_arn

        self.aws_groups = credentials.aws_groups
        self.aws_snapshot_accounts = credentials.aws_snapshot_accounts

        self.upload_svc = AWSUploadService(
            credentials.aws_image_access_key,
            credentials.aws_image_secret_access,
            credentials.aws_region,
        )

        self.publish_svc = AWSPublishService(
            credentials.aws_marketplace_access_key,
            credentials.aws_marketplace_secret_access,
            credentials.aws_region,
        )
        self.image_id = ""

    def _name_from_push_item(self, push_item: AmiPushItem) -> str:
        """
        Create an image name from the metadata provided.

        Args:
            push_item (AmiPushItem)
                The input push item.
        Returns:
            str: The image name from push item.
        """
        parts = []
        release = push_item.release

        if release.base_product is not None:
            parts.append(release.base_product)
            if release.base_version is not None:
                parts.append(release.base_version)

        parts.append(release.product)

        # Some attributes should be separated by underscores
        underscore_parts = []

        if release.version is not None:
            underscore_parts.append(release.version)

        underscore_parts.append(push_item.virtualization.upper())

        if release.type is not None:
            underscore_parts.append(release.type.upper())

        parts.append("_".join(underscore_parts))

        parts.append(release.date.strftime("%Y%m%d"))
        parts.append(release.arch)
        parts.append(str(release.respin))
        parts.append(push_item.volume.upper())

        return "-".join(parts)

    def _get_security_items(self, push_item: AmiPushItem) -> List[Dict[str, Any]]:
        """
        Convert AmiSecurityGroup to a List.

        Args:
            push_item (AmiPushItem)
                The input push item.
        Returns:
            List[Dict[str, Any]]: List of security groups.
        """
        security_groups = []
        for security_group in push_item.security_groups:
            sg = {
                "from_port": security_group.from_port,
                "ip_protocol": security_group.ip_protocol,
                "ip_ranges": security_group.ip_ranges.copy(),
                "to_port": security_group.to_port,
            }
            security_groups.append(sg)
        return security_groups

    def _format_release_notes(self, push_item: AmiPushItem) -> str:
        """
        Format release notes.

        Args:
            push_item (AmiPushItem)
                The input push item.
        Returns:
            str: The formatted release notes.
        """
        major_version = push_item.release.version.split(".")[0]
        release_notes_format = push_item.release_notes.format(
            major_version=major_version, major_minor=push_item.release.version
        )
        return release_notes_format

    @classmethod
    def from_credentials(cls, auth_data: Dict[str, Any]) -> 'AWSProvider':
        """
        Create an AWSProvider object using the incoming credentials.

        Args:
            auth_data (dict)
                Dictionary with the required data to instantiate the AWSCredentials object.
        Returns:
            A new instance of AWSProvider.
        """
        creds = AWSCredentials(**auth_data)
        return cls(creds)

    def _upload(self, push_item: AmiPushItem) -> Tuple[AmiPushItem, Any]:
        """
        Upload and import a disk image to AWS.

        If ship is not True, the image will only be available to internal accounts.
        Returns a tuple of the image id as provided by Amazon and its name.
        All the work is handled by the cloudimg library and it can take a
        considerable amount of time. The general workflow is as follows.
        1) Upload the bits via HTTP to AWS storage (S3)
        2) Import the uploaded file as an EC2 snapshot
        3) Register the snapshot as an AWS image (AMI)
        4) Modify permissions for the AMI
        Steps 1 and 2 will only be performed once per region per file.
        Different AMIs may be registered from the same snapshot during step 3.
        Each image type (hourly, access, etc) produces its own AMI.
        It is advantageous to not call this method in parallel for the same
        file because the cloudimg library is smart enough to skip lengthy steps
        such as the upload and snapshot registration.

        Args:
            push_item (AmiPushItem)
                The push item with the required data to upload the VHD image into Azure.
        Returns:
            The EC2 image with the data from uploaded image.
        """
        name = self._name_from_push_item(push_item)
        binfo = push_item.build_info
        LOG.info("Image name: %s", name)

        tags = {
            "nvra": f"{binfo.name}-{binfo.version}-{binfo.release}.{push_item.release.arch}",
            "name": push_item.build_info.name,
            "version": binfo.version,
            "release": binfo.release,
            "arch": push_item.release.arch,
            "buildid": push_item.build,
        }
        upload_metadata_kwargs = {
            "image_path": push_item.src,
            "image_name": name,
            "snapshot_name": name,
            "container": UPLOAD_CONTAINER_NAME,
            "description": push_item.description,
            "arch": push_item.release.arch,
            "virt_type": push_item.virtualization.upper(),
            "root_device_name": push_item.root_device,
            "volume_type": push_item.volume.upper(),
            "accounts": self.aws_groups or [],
            "snapshot_account_ids": self.aws_snapshot_accounts,
            "sriov_net_support": push_item.sriov_net_support,
            "ena_support": push_item.ena_support,
            "billing_products": [],
            "tags": tags,
        }
        LOG.debug("%s", upload_metadata_kwargs)
        metadata = AWSUploadMetadata(**upload_metadata_kwargs)

        res = self.upload_svc.publish(metadata)
        return push_item, res

    def _post_upload(self, push_item: AmiPushItem, upload_result: Any) -> Tuple[AmiPushItem, Any]:
        """
        Export the AMI Id for the uploaded image.

        Args:
            push_item (AmiPushItem)
                The original push item for uploading the VHD image.
            upload_result (str)
                The AMI upload properties

        Returns:
            The AMI Id for the uploaded image.
        """
        self.image_id = upload_result.id
        push_item_with_ami_id = evolve(push_item, image_id=upload_result.id)
        return push_item_with_ami_id, upload_result

    def _publish(
        self, push_item: AmiPushItem, nochannel: bool, overwrite: bool = False
    ) -> Tuple[AmiPushItem, Any]:
        """
        Associate and publish a VHD image into an AWS product.

        Args:
            push_item (AmiPushItem)
                The push item to associate and publish a VM image into an Azure product.
            nochannel (bool)
                Whether to keep draft or not.
            overwrite (bool, Optional)
                Whether to replace every image in the product with the given one or not.
                Defaults to ``False``
        """
        if push_item.release.base_product is not None:
            os_name = push_item.release.base_product
        else:
            os_name = push_item.build_info.name

        release = push_item.release
        release_date = release.date.strftime("%Y%m%d")
        respin = str(release.respin)

        version_mapping_kwargs = {
            "Version": {
                "VersionTitle": f"{push_item.release.version} {release_date}-{respin}",
                "ReleaseNotes": self._format_release_notes(push_item),
            },
            "DeliveryOptions": [
                {
                    "Details": {
                        "AmiDeliveryOptionDetails": {
                            "AmiSource": {
                                "AmiId": push_item.image_id,
                                "AccessRoleArn": self.aws_access_role_arn,
                                "UserName": push_item.user_name,
                                "OperatingSystemName": os_name.split("-")[0].upper(),
                                "OperatingSystemVersion": push_item.release.version,
                                "ScanningPort": push_item.scanning_port,
                            },
                            "UsageInstructions": push_item.usage_instructions,
                            "RecommendedInstanceType": push_item.recommended_instance_type,
                            "SecurityGroups": self._get_security_items(push_item),
                        }
                    }
                }
            ],
        }
        dest_string = ''.join(push_item.dest)
        version_mapping = AWSVersionMapping.from_json(version_mapping_kwargs)
        publish_metadata_kwargs = {
            "version_mapping": version_mapping,
            "marketplace_entity_type": push_item.marketplace_entity_type,
            "image_path": push_item.image_id,
            "architecture": push_item.release.arch,
            "destination": dest_string,
            "keepdraft": nochannel,
            "overwrite": overwrite,
        }
        metadata = AWSPublishMetadata(**publish_metadata_kwargs)
        res = self.publish_svc.publish(metadata)
        return push_item, res


register_provider(AWSProvider, "aws-na", "aws-emea")
