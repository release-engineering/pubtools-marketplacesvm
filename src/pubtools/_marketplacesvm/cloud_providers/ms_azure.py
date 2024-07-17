# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional, Set, Tuple

from attrs import asdict, evolve, field, frozen
from attrs.validators import instance_of
from cloudimg.ms_azure import AzurePublishingMetadata as AzureUploadMetadata
from cloudimg.ms_azure import AzureService as AzureUploadService
from cloudpub.ms_azure import AzurePublishingMetadata as AzurePublishMetadata
from cloudpub.ms_azure import AzureService as AzurePublishService
from pushsource import VHDPushItem

from .base import UPLOAD_CONTAINER_NAME, CloudCredentials, CloudProvider, register_provider

LOG = logging.getLogger("pubtools.marketplacesvm")


@frozen
class AzureCredentials(CloudCredentials):
    """Represent the credentials for AzureProvider."""

    azure_publisher_name: str = field(alias="AZURE_PUBLISHER_NAME", validator=instance_of(str))
    """The publisher name."""

    azure_tenant_id: str = field(alias="AZURE_TENANT_ID", validator=instance_of(str))
    """Tenant ID for Azure Marketplace."""

    azure_client_id: str = field(alias="AZURE_CLIENT_ID", validator=instance_of(str))
    """Client ID for Azure Marketplace."""

    azure_api_secret: str = field(alias="AZURE_API_SECRET", validator=instance_of(str))
    """API secret for Azure Marketplace."""

    azure_storage_connection_string: str = field(
        alias="AZURE_STORAGE_CONNECTION_STRING", validator=instance_of(str)
    )
    """The storage account connection string for uploading the image."""

    azure_api_version: Optional[str] = field(alias="AZURE_API_VERSION", default="2022-07-01")
    """The graph API version."""

    @property
    def credentials(self) -> Dict[str, str]:
        """Return the credentials as a dictionary."""
        return {k.upper(): v for k, v in asdict(self).items() if k != "cloud_name"}


class AzureDestinationBorg:
    """
    Borg to keep track of the Azure destinations which were changed.

    Since we don't want to touch an offer which its original state is "draft" we need to keep
    track of the visited offers to mark them as "safe".

    This is required because whenever we touch a single plan to assign the VM image we're also
    changing the offer status to "draft". Supposing the existence of "Offer-A", which has 2 or more
    plans, whenever we change the first plan the offer state would be "draft" thus leaving it
    impossible for the program to know, when adjusting the second offer, whether the "draft" state
    comes from a change in the offer before we touch the first plan or not.

    In order to solve this issue we check the offer before changing anything and mark it in the
    Borg as "visited" to have a clear state of what "draft" may represent.

    See also: https://baites.github.io/computer-science/patterns/singleton-series/2018/06/11/python-borg-and-the-new-metaborg.html
    """  # noqa: E501

    _shared_state: Dict[str, Any] = {}

    def __new__(cls):
        """Instantiate a new borg object with the shared state."""
        inst = super().__new__(cls)
        inst.__dict__ = cls._shared_state
        return inst

    @property
    def destinations(self) -> Set[Any]:
        """Provide a shared set of destinations."""
        if not hasattr(self, "_destinations"):
            self._destinations: Set[Any] = set()
        return self._destinations


class AzureProvider(CloudProvider[VHDPushItem, AzureCredentials]):
    """The Azure marketplace provider."""

    def __init__(self, credentials: AzureCredentials) -> None:
        """
        Create an instance of AzureProvider.

        Args:
            credentials (AzureCredentials)
                credentials to use the Azure API.
        """
        self.upload_svc = AzureUploadService.from_connection_string(
            credentials.azure_storage_connection_string
        )
        self.publish_svc = AzurePublishService(credentials.credentials)
        self._borg = AzureDestinationBorg()

    def _name_from_push_item(self, push_item: VHDPushItem) -> str:
        """
        Construct an image name from the given push item.

        Args:
            push_item (VHDPushItem)
                The input push item.
        Returns:
            str: The image name from push item.
        """
        parts = []
        release = push_item.release

        # Base product is defined only for layered products.
        if release.base_product is not None:
            parts.append(release.base_product)
            # The base_version may exist only if base_product is set.
            if release.base_version is not None:
                parts.append(release.base_version)

        parts.append(release.product)

        # Some attributes should be separated by underscores
        underscore_parts = []

        if release.version is not None:
            underscore_parts.append(release.version)

        underscore_parts.append(push_item.generation.upper())

        if release.type is not None:
            underscore_parts.append(release.type.upper())

        parts.append("_".join(underscore_parts))

        parts.append(release.date.strftime("%Y%m%d"))
        parts.append(release.arch)
        parts.append(str(release.respin))

        return "-".join(parts)

    def _generate_disk_version(self, push_item: VHDPushItem) -> str:
        """
        Generate a version number for DiskVersion based on existing information.

        The version number should be in the format "{int}.{int}.{int}"

        In our workflow the version number is generated as:

            x.y.YYYYMMDDHHmm

        Where:
            - ``x`` is the product major version
            - ``y`` is the product minor version
            - ``YYYYMMDDHHmm`` is the current date

        Args:
            metadata
                The incoming push item to calculate the version number.
        Returns:
            The automatically generated version number.
        """
        current_date = datetime.now().strftime("%Y%m%d%H")

        # Get the version from PushItem's build_info
        version = push_item.build_info.version
        version_split = version.split(".")

        # Return the new disk_version
        return f"{version_split[0]}.{version_split[1]}.{current_date}"

    @classmethod
    def from_credentials(cls, auth_data: Dict[str, Any]) -> 'AzureProvider':
        """
        Create an AzureProvider object using the incoming credentials.

        Args:
            auth_data (dict)
                Dictionary with the required data to instantiate the AzureCredentials object.
        Returns:
            A new instance of AzureProvider.
        """
        creds = AzureCredentials(**auth_data)
        return cls(creds)

    def _upload(
        self, push_item: VHDPushItem, custom_tags: Optional[Dict[str, str]] = None, **kwargs
    ) -> Tuple[VHDPushItem, Any]:
        """
        Upload a VHD image into Azure.

        Args:
            push_item (VHDPushItem)
                The push item with the required data to upload the VHD image into Azure.
            custom_tags (dict, optional)
                Dictionary with keyword values to be added as custom tags.
        Returns:
            The BlobProperties with the data from uploaded image.
        """
        binfo = push_item.build_info
        tags = {
            "nvra": f"{binfo.name}-{binfo.version}-{binfo.release}.{push_item.release.arch}",
            "name": push_item.build_info.name,
            "version": push_item.build_info.version,
            "release": push_item.build_info.release,
            "arch": push_item.release.arch,
            "buildid": str(push_item.build_info.id),
        }
        if custom_tags:
            LOG.debug(f"Setting up custom tags: {custom_tags}")
            tags.update(custom_tags)

        # For Coreos-Assembler images change the version and nvra tag
        # so it have the full version like "414.92.202405282322"
        # instead of 4.14
        if push_item.src.startswith("https://"):
            tags["version"] = push_item.build.split("-")[2]
            tags["nvra"] = (
                f"{binfo.name}-{tags['version']}-{binfo.release}.{push_item.release.arch}"  # noqa: E501
            )
        upload_metadata_kwargs = {
            "image_path": push_item.src,
            "image_name": self._name_from_push_item(push_item),
            "container": UPLOAD_CONTAINER_NAME,
            "description": push_item.description,
            "arch": push_item.release.arch,
            "tags": tags,
        }
        metadata = AzureUploadMetadata(**upload_metadata_kwargs)
        res = self.upload_svc.publish(metadata)
        return push_item, res

    def _post_upload(
        self, push_item: VHDPushItem, upload_result: Any, **kwargs
    ) -> Tuple[VHDPushItem, Any]:
        """
        Export the SAS URI for the uploaded image.

        Args:
            push_item (VHDPushItem)
                The original push item for uploading the VHD image.
            upload_result (BlobProperties)
                The uploaded blob properties

        Returns:
            The SAS URI for the uploaded image.
        """
        sas_uri = self.upload_svc.get_blob_sas_uri(upload_result)
        push_item_with_sas = evolve(push_item, sas_uri=sas_uri)
        return push_item_with_sas, upload_result

    def _pre_publish(self, push_item: VHDPushItem, **kwargs) -> Tuple[VHDPushItem, Any]:
        """
        Execute the ``self._publish`` with ``nochannel == True`` to only associate the images.

        At this point we're not publishing, just adding the VHD's SAS URI into the Offer's draft.

        Args:
            push_item (VHDPushItem)
                The push item to associate a VM image into Azure's product.

        Returns:
            The push item with the result of the operation.
        """
        return self._publish(push_item=push_item, nochannel=True, **kwargs)

    def _publish(
        self,
        push_item: VHDPushItem,
        nochannel: bool,
        overwrite: bool = False,
        **kwargs,
    ) -> Tuple[VHDPushItem, Any]:
        """
        Associate and publish a VHD image into an Azure product.

        Args:
            push_item (VHDPushItem)
                The push item to associate and publish a VM image into an Azure product.
            nochannel (bool)
                Whether to keep draft or not.
            overwrite (bool, optional)
                Whether to replace every image in the product with the given one or not.
                Defaults to ``False``
        """
        if not push_item.disk_version:
            push_item = evolve(push_item, disk_version=self._generate_disk_version(push_item))

        destination = push_item.dest[0]
        self.ensure_offer_is_writable(destination, nochannel)

        publish_metadata_kwargs = {
            "disk_version": push_item.disk_version,
            "sku_id": push_item.sku_id,
            "generation": push_item.generation or "V2",
            "support_legacy": push_item.support_legacy or False,
            "recommended_sizes": push_item.recommended_sizes or [],
            "legacy_sku_id": push_item.legacy_sku_id,
            "image_path": push_item.sas_uri,
            "architecture": push_item.release.arch,
            "destination": destination,
            "keepdraft": nochannel,
            "overwrite": overwrite,
        }
        metadata = AzurePublishMetadata(**publish_metadata_kwargs)
        res = self.publish_svc.publish(metadata)
        return push_item, res

    def _post_publish(
        self, push_item: VHDPushItem, publish_result: Any, nochannel, **kwargs
    ) -> Tuple[VHDPushItem, Any]:
        """
        Add release_date with after image is published.

        Args:
            push_item (VHDPushItem)
                The original push item for uploading the image.
            publish_result (Any)
                The publish result.
            nochannel (bool)
                Is this a nochannel publish.

        Returns:
            Tuple of PushItem and Publish results.
        """
        if nochannel:
            return push_item, publish_result
        container = UPLOAD_CONTAINER_NAME
        name = os.path.basename(push_item.src).rstrip(".xz")

        blob = self.upload_svc.get_object_by_name(container, name)
        blob_tags = blob.get_blob_tags()

        blob_tags["release_date"] = datetime.now().strftime("%Y%m%d%H::%M::%S")
        update_res = blob.set_blob_tags(blob_tags)

        return push_item, update_res

    def ensure_offer_is_writable(self, destination: str, nochannel: bool) -> None:
        """
        Ensure the offer can be modified and published by this tool.

        If the offer's initial state is "draft" it means someone made manual changes in the webui
        and we cannot proceed. However, this is just true if the offer hasn't being changed by this
        tool, thus we use the Borg to inform us whether we're safe to proceed or not.

        Since during the `publish` phase we need to call it two time (one with keep_draft as True to
        associate the images to possible multiple plans of the same offer, the other to submit) we
        will have a "draft" state that is caused by the tooling, hence the Borg to keep track of
        what it touched to disconsider this "draft" as a signal of manual changes.
        """
        offer_name = destination.split("/")[0]
        product = self.publish_svc.get_product_by_name(offer_name)

        # Here we could have the state as: "draft", "preview" or "live"
        state = product.target.targetType

        # During pre-push mode we need to ensure the "draft" state is not the initial offer state.
        # If the offer name is inside Borg's destination it means that the "draft" state was caused
        # by this tool instead of manual changes.
        # The only "draft" state that we should raise an error is when the offer name is not in
        # the borg and the nochannel is True, meaning this state comes from a manual change.
        if nochannel is True and offer_name not in self._borg.destinations:
            self._borg.destinations.add(offer_name)
            if state == "draft":
                raise RuntimeError(
                    f"Can't update the offer {offer_name} as it's already being changed."
                )


register_provider(AzureProvider, "azure-na", "azure-emea")
