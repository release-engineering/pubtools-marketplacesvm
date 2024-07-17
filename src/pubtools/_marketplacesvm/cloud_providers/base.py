# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import os
import sys
from abc import ABC, abstractmethod
from typing import Any, Dict, Generic, NoReturn, Optional, Tuple, Type, TypeVar

if sys.version_info >= (3, 8):
    from typing import TypedDict  # pragma: no cover
else:
    from typing_extensions import TypedDict  # pragma: no cover

from attrs import Attribute, field, frozen
from attrs.validators import instance_of
from pushsource import VMIPushItem

log = logging.getLogger("pubtools.marketplacesvm")

T = TypeVar("T", bound=VMIPushItem)

UPLOAD_CONTAINER_NAME = os.getenv("UPLOAD_CONTAINER_NAME", "pubupload")

__CLOUD_PROVIDERS = {}


class MarketplaceAuth(TypedDict):
    """
    Represent the incoming marketplace auth data.

    This dictionary is used to identify the expected provider and build its CloudCredentials.
    """

    marketplace_account: str
    auth: Dict[str, Any]


@frozen
class CloudCredentials:
    """The base class for a cloud provider credentials."""

    cloud_name: str = field(
        validator=instance_of(str),
        converter=lambda x: x.lower() if isinstance(x, str) else x,
    )
    """The cloud name from StArMap."""

    @cloud_name.validator
    def _validate_cloud_name(self, attribute: Attribute, value: str):
        """Validate whether the cloud name has a valid suffix."""
        valid_suffix_list = ["-na", "-emea", "-storage"]
        for suffix in valid_suffix_list:
            if value.endswith(suffix):
                return
        raise ValueError(f"Invalid value for {attribute.name}: missing region.")


C = TypeVar("C", bound=CloudCredentials)


class CloudProvider(ABC, Generic[T, C]):
    """
    The base class for cloud marketplaces providers.

    It provides the common interface for uploading
    and publishing a VMI image into a cloud marketplace.

    Each subclass must implement all private abstract methods and optionally
    implement the other private methods.

    The public methods are not inteded to be overriden.
    """

    #
    # Subclasses must implement
    #

    @classmethod
    @abstractmethod
    def from_credentials(cls, auth_data: Dict[str, Any]) -> 'CloudProvider':
        """
        Abstract method for a factory of a CloudProvider subclass using the given credentials.

        Args:
            auth_data (dict)
                Dictionary with the required data to instantiate the object.
        Returns:
            The requested object
        """

    @abstractmethod
    def _upload(
        self, push_item: T, custom_tags: Optional[Dict[str, str]] = None, **kwargs
    ) -> Tuple[T, Any]:
        """
        Abstract method for uploading a VM image into a public cloud provider.

        Args:
            push_item (VMIPushItem)
                The push item to upload the image into a cloud provider.
            custom_tags (dict, optional)
                Dictionary with keyword values to be added as custom tags.
        Returns:
            The resulting data from upload.
        """

    @abstractmethod
    def _pre_publish(self, push_item: T, **kwargs) -> Tuple[T, Any]:
        """
        Abstract method for optional routines before publishing.

        Args:
            push_item (VMIPushItem)
                The push item process.

        Returns:
            The processed push item and the processing result.
        """

    @abstractmethod
    def _publish(
        self,
        push_item: T,
        nochannel: bool,
        overwrite: bool = False,
        **kwargs,
    ) -> Tuple[T, Any]:
        """
        Abstract method for associating and publishing a VM image with a product.

        Args:
            push_item (VMIPushItem)
                The push item to associate and publish a VM image into a product.
            nochannel (bool)
                Whether to keep draft or not.
            overwrite (bool, optional)
                Whether to replace every image in the product with the given one or not.
                Defaults to ``False``
        """

    #
    # Subclasses can implement
    #

    def _post_upload(self, push_item: T, upload_result: Any, **kwargs) -> Tuple[T, Any]:
        """
        Define the default method for post upload actions.

        Args:
            push_item (VMIPushItem)
                The push item for post upload actions.
            upload_result (object)
                The result data from upload.
        Returns:
            The upload result data.
        """
        return push_item, upload_result

    def _post_publish(
        self, push_item: T, publish_result: Any, nochannel: bool, **kwargs
    ) -> Tuple[T, Any]:
        """
        Define the default method for post publishing actions.

        Args:
            push_item (VMIPushItem)
                The push item to associate and publish a VM image into a product.
            publish_result (Any)
                The resulting data from publish.
            nochannel (bool)
                Is this a nochannel publish.
        Returns:
            The publish result data.
        """
        return push_item, publish_result

    #
    # Public interfaces - not intended to be changed by subclasses
    #
    @staticmethod
    def raise_error(exception: Type[Exception], message=str) -> NoReturn:
        """
        Log and raise an error.

        Args
            exception (Exception)
                The exception type to raise.
            message (str)
                The error message.
        Raises:
            Exception: the requested exception with the incoming message.
        """
        log.error(message)
        raise exception(message)

    def upload(
        self, push_item: T, custom_tags: Optional[Dict[str, str]] = None, **kwargs
    ) -> Tuple[T, Any]:
        """
        Upload the VM image into a pulic cloud provider.

        Args:
            push_item (VMIPushItem)
                The push item to upload the image into a cloud provider.
            custom_tags (dict, optional)
                Dictionary with keyword values to be added as custom tags.
        Returns:
            object: The upload result data.
        """
        pi, res = self._upload(push_item, custom_tags=custom_tags, **kwargs)
        return self._post_upload(pi, res, **kwargs)

    def pre_publish(self, push_item: T, **kwargs):
        """
        Execute an optional custom routine before publishing.

        Args:
            push_item (VMIPushItem)
                The push item to process.
        Returns:
            The processed push item and the processing result.
        """
        return self._pre_publish(push_item, **kwargs)

    def publish(
        self,
        push_item: T,
        nochannel: bool,
        overwrite: bool = False,
        **kwargs,
    ) -> Tuple[T, Any]:
        """
        Associate an existing VM image with a product and publish the changes.

        Args:
            push_item (VMIPushItem)
                The push_item to associate and publish a VM image into a product.
            nochannel (bool)
                Do as much as it can before publishing when set to `True` or publish when
                set to `False`.
            overwrite (bool, optional)
                Whether set only the requested image and erase everything else or not.
        Returns:
            object: The publish result data.
        """
        pi, res = self._publish(push_item, nochannel, overwrite, **kwargs)
        return self._post_publish(pi, res, nochannel, **kwargs)


P = TypeVar('P', bound=CloudProvider)


def register_provider(provider: Type[P], *args) -> None:
    """
    Register a cloud provider with its marketplace account aliases.

    Args:
        provider:
            The subclass of CloudProvider which implements the provider for the given aliases
        *aliases:
            List of marketplace account aliases corresponding to the `provider`.
    """
    for alias in args:
        __CLOUD_PROVIDERS.update({alias: provider})


def get_provider(auth_data: MarketplaceAuth) -> Any:
    """
    Return the required provider by its marketplace_account name.

    Args:
        auth_data (dict)
            The marketplace authentication data with its account alias.

    Returns:
        The required instance of a CloudProvider.
    """
    marketplace_account = auth_data.get("marketplace_account")
    auth = auth_data.get("auth")
    if not marketplace_account or not auth or not isinstance(auth, dict):
        message = "Missing or invalid credentials."
        log.error(message)
        raise RuntimeError(message)

    auth.update({"cloud_name": marketplace_account})
    klass = __CLOUD_PROVIDERS.get(marketplace_account)

    if not klass or not issubclass(klass, CloudProvider):
        message = f"No provider found for {marketplace_account}"
        log.error(message)
        raise RuntimeError(message)

    return klass.from_credentials(auth)
