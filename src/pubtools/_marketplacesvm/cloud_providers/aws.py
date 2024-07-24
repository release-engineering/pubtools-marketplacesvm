import logging
import os
from collections import namedtuple
from datetime import datetime
from functools import partial
from typing import Any, Dict, List, Optional, Tuple

from attrs import asdict, evolve, field, frozen
from attrs.validators import deep_iterable, instance_of
from cloudimg.aws import AWSDeleteMetadata as AWSDeleteMetadata
from cloudimg.aws import AWSPublishingMetadata as AWSUploadMetadata
from cloudimg.aws import AWSService as AWSUploadService
from cloudpub.aws import AWSProductService as AWSPublishService
from cloudpub.aws import AWSVersionMetadata as AWSPublishMetadata
from cloudpub.models.aws import VersionMapping as AWSVersionMapping
from pushsource import AmiPushItem

from .base import UPLOAD_CONTAINER_NAME, CloudCredentials, CloudProvider, register_provider

LOG = logging.getLogger("pubtools.marketplacesvm")
UploadResult = namedtuple("UploadResult", "id")  # NOSONAR


def name_from_push_item(push_item: AmiPushItem) -> str:
    """
    Create an image name from the metadata provided.

    Args:
        push_item (AmiPushItem)
            The input push item.
    Returns:
        str: The image name from push item.
    """

    def get_2_digits(version: str) -> str:
        v = version.split(".")[:2]
        return ".".join(v)

    parts = []
    release = push_item.release

    if release.base_product is not None:
        parts.append(release.base_product)
        if release.base_version is not None:
            parts.append(get_2_digits(release.base_version))

    parts.append(release.product)

    # Some attributes should be separated by underscores
    underscore_parts = []

    if release.version is not None:
        underscore_parts.append(get_2_digits(release.version))

    underscore_parts.append(push_item.virtualization.upper())

    if release.type is not None:
        underscore_parts.append(release.type.upper())

    parts.append("_".join(underscore_parts))

    parts.append(release.date.strftime("%Y%m%d"))
    parts.append(release.arch)
    parts.append(str(release.respin))

    # The parts below are used for community AMIs only
    if push_item.billing_codes is not None:
        parts.append(push_item.billing_codes.name)
        parts.append(push_item.volume.upper())

    return "-".join(parts)


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

    aws_accounts: Optional[List[str]] = field(
        alias="AWS_ACCOUNTS",
        validator=deep_iterable(
            member_validator=instance_of(str),
            iterable_validator=instance_of(list),
        ),
        factory=list,
    )
    """Accounts to share image with. Defaults to empty list."""

    aws_snapshot_accounts: Optional[List[str]] = field(
        alias="AWS_SNAPSHOT_ACCOUNTS",
        validator=deep_iterable(
            member_validator=instance_of(str),
            iterable_validator=instance_of(list),
        ),
        factory=list,
    )
    """Snapshot accounts to share to. Defaults to empty list."""

    aws_region: str = field(alias="AWS_REGION", validator=instance_of(str), default="us-east-1")
    """AWS Region. Defaults to 'us-east-1'."""

    aws_s3_bucket: Optional[str] = field(
        alias="AWS_S3_BUCKET",
        validator=instance_of(str),
        default=UPLOAD_CONTAINER_NAME,
    )
    """AWS S3 bucket to upload the VM image.
       When not set it will use the value from ``UPLOAD_CONTAINER_NAME``.
    """

    @property
    def credentials(self) -> Dict[str, str]:
        """Return the credentials as a dictionary."""
        return {k.upper(): v for k, v in asdict(self).items() if k != "cloud_name"}


class AWSProvider(CloudProvider[AmiPushItem, AWSCredentials]):
    """The AWS marketplace provider."""

    _TIMEOUT_ATTEMPTS = int(os.environ.get("MARKETPLACESVM_PUSH_AWS_TIMEOUT_ATTEMPTS", "288"))
    _TIMEOUT_INTERVALS = int(os.environ.get("MARKETPLACESVM_PUSH_AWS_TIMEOUT_INTERVALS", "600"))

    ARCH_ALIASES: Dict[str, str] = {"aarch64": "arm64"}
    """Dictionary of aliases for architecture names between brew and AWS."""

    def __init__(self, credentials: AWSCredentials) -> None:
        """
        Create an instance of AWSProvider.

        Args:
            credentials (AWSCredentials)
                credentials to use the AWS Boto3.
        """
        self.aws_access_role_arn = credentials.aws_access_role_arn

        self.aws_groups = credentials.aws_groups
        self.aws_accounts = credentials.aws_accounts
        self.aws_snapshot_accounts = credentials.aws_snapshot_accounts

        self.upload_svc_partial = partial(
            AWSUploadService, credentials.aws_image_access_key, credentials.aws_image_secret_access
        )
        self.default_region = credentials.aws_region

        self.publish_svc = AWSPublishService(
            credentials.aws_marketplace_access_key,
            credentials.aws_marketplace_secret_access,
            credentials.aws_region,
            self._TIMEOUT_ATTEMPTS,
            self._TIMEOUT_INTERVALS,
        )
        self.image_id = ""
        self.s3_bucket = credentials.aws_s3_bucket or UPLOAD_CONTAINER_NAME

    def _get_security_items(self, push_item: AmiPushItem) -> List[Dict[str, Any]]:
        """
        Convert a list of AmiSecurityGroup to a list of dictionary.

        Args:
            push_item (AmiPushItem)
                The input push item.
        Returns:
            List[Dict[str, Any]]: List of security groups.
        """
        security_groups = []
        for sg in push_item.security_groups:
            data = asdict(sg)
            data["ip_ranges"] = [ip for ip in sg.ip_ranges]
            security_groups.append(data)
        return security_groups

    def _format_version_info(self, str_to_format: str, version_str: str) -> str:
        """
        Format a string with versioning info.

        Args:
            str_to_format (str)
                String to format with version information.
            version_str (str)
                String with version info ie 8.1.
        Returns:
            str: The formatted str.
        """
        splitted_version = version_str.split(".")
        major_version = splitted_version[0]
        minor_version = splitted_version[1]
        major_minor = ".".join(splitted_version[0:2])
        formatted_str = str_to_format.format(
            major_minor=major_minor,
            major_version=major_version,
            minor_version=minor_version,
        )
        return formatted_str

    def _get_access_endpoint_url(self, push_item: AmiPushItem) -> Optional[Dict[str, Any]]:
        """
        Format a string with versioning info.

        Args:
            str_to_format (str)
                String to format with version information.
            version_str (str)
                String with version info ie 8.1.
        Returns:
            str: The formatted str.
        """
        if push_item.access_endpoint_url:
            return {
                "port": push_item.access_endpoint_url.port,
                "protocol": push_item.access_endpoint_url.protocol,
            }
        return None

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

    def _copy_image_from_ami_catalog(self, push_item: AmiPushItem, tags: Dict[str, str]):
        """
        Copy AMI from AMI-Catalog (AWS-Marketplace AMIs and Community-AMIs) to account.

        Args:
            push_item(AmiPushItem): The push item containing the source of AMI ID.
        Returns:
            ami_id (namedtuple): An named tuple object which contains AMI ID.
        Raises:
            RuntimeError if AMI is not found.
        """
        upload_svc = self.upload_svc_partial(region=push_item.region)

        img = upload_svc.get_image_from_ami_catalog(push_item.src)
        if img is None:
            raise RuntimeError("AMI not found.")

        # Search if the AMI is already in the Account
        ami = upload_svc.get_image_by_name(push_item.build)
        if ami:
            LOG.info("AMI already exits in account.Skipping Copying AMI.")
            result = UploadResult(ami.id)
        else:
            LOG.info("AMI not found in account. Copying ami to account.")

            copy_result = upload_svc.copy_ami(
                image_id=push_item.src,
                image_name=push_item.build,
                image_region=push_item.region,
            )
            result = UploadResult(copy_result["ImageId"])
        image = upload_svc.get_image_by_id(result.id)
        upload_svc.tag_image(image, tags)
        return result

    def _upload(
        self,
        push_item: AmiPushItem,
        custom_tags: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> Tuple[AmiPushItem, Any]:
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
                The push item with the required data to upload the AMI image into AWS.
            custom_tags (dict, optional)
                Dictionary with keyword values to be added as custom tags.
            groups (list, optional)
                List of groups to share the image with. Defaults to ``self.aws_groups``.
            accounts (list, optional)
                List of accounts to share the image with. Defaults to ``self.aws_accounts.``
            snapshot_accounts (list, optional)
                List of accounts to share the snapshot with. Defaults
                to ``self.aws_snapshot_accounts``.
            container (str, optional)
                The S3 container name to upload the image into. Defaults to ``self.s3_bucket``.
        Returns:
            The EC2 image with the data from uploaded image.
        """
        # Check if the AMI is already created for this push item.
        name = name_from_push_item(push_item)
        binfo = push_item.build_info
        default_groups = self.aws_groups or []
        groups = kwargs.get("groups") or default_groups
        default_accounts = self.aws_accounts or []
        accounts = kwargs.get("accounts") or default_accounts
        default_snapshot_accounts = self.aws_snapshot_accounts or []
        snapshot_accounts = kwargs.get("snapshot_accounts") or default_snapshot_accounts
        container = kwargs.get("container") or self.s3_bucket
        LOG.info("Image name: %s | Sharing groups: %s", name, groups)
        # Update some items in push_item
        region = push_item.region or self.default_region
        push_item = evolve(push_item, region=region)
        push_item = evolve(push_item, name=name)

        tags = {
            "nvra": f"{binfo.name}-{binfo.version}-{binfo.release}.{push_item.release.arch}",
            "name": push_item.build_info.name,
            "version": binfo.version,
            "release": binfo.release,
            "arch": push_item.release.arch,
            "buildid": str(push_item.build_info.id),
        }
        if custom_tags:
            LOG.debug(f"Setting up custom tags: {custom_tags}")
            tags.update(custom_tags)

        if push_item.src.startswith("ami"):
            tags["version"] = push_item.build.split("-")[2]
            tags["nvra"] = (
                f"{binfo.name}-{tags['version']}-{binfo.release}.{push_item.release.arch}"  # noqa: E501
            )

            result = self._copy_image_from_ami_catalog(push_item, tags=tags)
            return push_item, result

        upload_metadata_kwargs = {
            "image_path": push_item.src,
            "image_name": name,
            "snapshot_name": name,
            "container": container,
            "description": push_item.description,
            "arch": self.ARCH_ALIASES.get(push_item.release.arch, push_item.release.arch),
            "virt_type": push_item.virtualization,
            "root_device_name": push_item.root_device,
            "volume_type": push_item.volume,
            "accounts": accounts,
            "groups": groups,
            "snapshot_account_ids": snapshot_accounts,
            "sriov_net_support": push_item.sriov_net_support,
            "ena_support": push_item.ena_support,
            "billing_products": [],
            "tags": tags,
        }
        if push_item.boot_mode:
            upload_metadata_kwargs.update({"boot_mode": push_item.boot_mode.value})
        if push_item.billing_codes:
            upload_metadata_kwargs.update({"billing_products": push_item.billing_codes.codes})

        LOG.debug("%s", upload_metadata_kwargs)
        metadata = AWSUploadMetadata(**upload_metadata_kwargs)

        res = self.upload_svc_partial(region=push_item.region).publish(metadata)
        return push_item, res

    def _post_upload(
        self, push_item: AmiPushItem, upload_result: Any, **kwargs
    ) -> Tuple[AmiPushItem, Any]:
        """
        Post upload activities currently sets the image Id.

        Args:
            push_item (AmiPushItem)
                The original push item for uploading the AMI image.
            upload_result (str)
                The AMI upload properties

        Returns:
            Tuple of PushItem and Upload results.
        """
        self.image_id = upload_result.id
        push_item_with_ami_id = evolve(push_item, image_id=upload_result.id)
        return push_item_with_ami_id, upload_result

    def _pre_publish(self, push_item: AmiPushItem, **kwargs) -> Tuple[AmiPushItem, Any]:
        """Return the push item as is since this step is not required for AWS.

        Args:
            push_item (AmiPushItem)
                The incoming push item.

        Returns:
            Tuple[AmiPushItem, Any]
                The incoming push item and the dict with received parameters.
        """
        LOG.info("Checking for active changesets in: %s", push_item.dest[0])
        self.publish_svc.wait_active_changesets(push_item.dest[0])
        return push_item, kwargs

    def _publish(
        self,
        push_item: AmiPushItem,
        nochannel: bool,
        overwrite: bool = False,
        **kwargs,
    ) -> Tuple[AmiPushItem, Any]:
        """
        Associate and publish a AMI image into an AWS product.

        Args:
            push_item (AmiPushItem)
                The push item to associate and publish a VM image into an AWS product.
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

        if push_item.release.base_version is not None:
            os_version = push_item.release.base_version
        else:
            os_version = push_item.release.version

        release = push_item.release
        release_date = release.date.strftime("%Y%m%d")
        respin = str(release.respin)

        version_title = (
            push_item.marketplace_title or f"{push_item.release.version} {release_date}-{respin}"
        )

        if self._check_version_exists(version_title, push_item.dest[0]):
            LOG.info("Version already exists in AWS: %s", version_title)
            return push_item, {}

        version_mapping_kwargs = {
            "Version": {
                "VersionTitle": version_title,
                "ReleaseNotes": self._format_version_info(
                    push_item.release_notes, push_item.release.version
                ),
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
                                "OperatingSystemVersion": os_version,
                                "ScanningPort": push_item.scanning_port,
                            },
                            "UsageInstructions": self._format_version_info(
                                push_item.usage_instructions, push_item.release.version
                            ),
                            "RecommendedInstanceType": push_item.recommended_instance_type,
                            "SecurityGroups": self._get_security_items(push_item),
                            "AccessEndpointUrl": self._get_access_endpoint_url(push_item),
                        }
                    }
                }
            ],
        }

        version_mapping = AWSVersionMapping.from_json(version_mapping_kwargs)
        publish_metadata_kwargs = {
            "version_mapping": version_mapping,
            "marketplace_entity_type": push_item.marketplace_entity_type,
            "image_path": push_item.image_id,
            "architecture": self.ARCH_ALIASES.get(push_item.release.arch, push_item.release.arch),
            "destination": push_item.dest[0],
            "keepdraft": nochannel,
            "overwrite": overwrite,
        }

        LOG.debug("%s", publish_metadata_kwargs)
        metadata = AWSPublishMetadata(**publish_metadata_kwargs)
        res = self.publish_svc.publish(metadata)
        return push_item, res

    def _post_publish(
        self, push_item: AmiPushItem, publish_result: Any, nochannel: bool, **kwargs
    ) -> Tuple[AmiPushItem, Any]:
        """
        Post publishing activities currently restricts older versions.

        Args:
            push_item (AmiPushItem)
                The original push item for uploading the AMI image.
            publish_result (str)
                The AMI publish properties
            nochannel (bool)
                Is this a nochannel publish.
            restrict_version (bool, Optional)
                Whether to restrict the version and remove the accompanying AMI/Snapshot.
            restrict_major (int, Optional)
                How many major versions should there be for this product.
            restrict_minor (int, Optional)
                How many minor versions should there be for this product.

        Returns:
            Tuple of PushItem and Publish results.
        """
        if nochannel:
            return push_item, publish_result
        region = push_item.region or self.default_region

        upload_svc = self.upload_svc_partial(region=region)
        image = upload_svc.get_image_by_id(self.image_id)
        release_date_tag = {"release_date": datetime.now().strftime("%Y%m%d%H::%M::%S")}
        upload_svc.tag_image(image, release_date_tag)
        restrict_version = kwargs.get("restrict_version", False)
        restrict_major = kwargs.get("restrict_major")
        restrict_minor = kwargs.get("restrict_minor")

        if restrict_version:
            LOG.info(
                "Starting to restrict versions: restrict_major = %s, restrict_minor = %s",
                restrict_major,
                restrict_minor,
            )

            restricted_amis = self.publish_svc.restrict_versions(
                push_item.dest[0], push_item.marketplace_entity_type, restrict_major, restrict_minor
            )

            LOG.info("Found AMIs to restrict: %s", restricted_amis)
            self._remove_amis(restricted_amis, region)

        return push_item, publish_result

    def _check_version_exists(self, publishing_version: str, entity_id: str) -> bool:
        """
        Check if a version exists in a product already in AWS.

        Args:
            publishing_version (str)
                Version to be checked against already published targets.
            entity_id (str)
                The entity id of the product to check against

        Returns:
            Bool of whether it exists or not.
        """
        current_versions = self.publish_svc.get_product_versions(entity_id)

        matching_version_list = [v for t, v in current_versions.items() if publishing_version in t]

        return len(matching_version_list) > 0

    def _remove_amis(self, restricted_amis: List[str], region: str) -> None:
        """
        Check if a version exists in a product already in AWS.

        Args:
            restricted_amis (list[str])
                A list of restricted amis to delete.
            region (str):
                The region in which the AMI is registered.
        """
        for ami_id in restricted_amis:
            delete_metadata_kwargs = {
                "image_id": ami_id,
            }

            LOG.debug("Deleting AMI: %s", delete_metadata_kwargs)
            metadata = AWSDeleteMetadata(**delete_metadata_kwargs)

            self.upload_svc_partial(region=region).delete(metadata)


register_provider(
    AWSProvider, "aws-na", "aws-emea", "aws-us-storage", "aws-us-gov-storage", "aws-china-storage"
)
