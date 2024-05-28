import base64
import json
import logging
import os
import threading
from argparse import ArgumentParser
from typing import Dict

from ..arguments import from_environ
from ..cloud_providers import CloudProvider, MarketplaceAuth, get_provider
from .base import Service

log = logging.getLogger("pubtools.marketplacesvm")


class CloudService(Service):
    """
    Define the service for uploading and publishing a VM Image into a cloud marketplace.

    The service client is returned when the ``credentials`` is provided.
    """

    def __init__(self, *args, **kwargs) -> None:
        """Instantiate a CloudService object."""
        self._instances: Dict[str, CloudProvider] = {}
        self._creds: Dict[str, MarketplaceAuth] = {}
        self._lock = threading.Lock()
        super(CloudService, self).__init__(*args, **kwargs)

    def add_service_args(self, parser: ArgumentParser) -> None:
        """
        Add the required CLI arguments for CloudService.

        Args:
            parser (ArgumentParser)
                The parser to include the additional arguments.
        """
        super(CloudService, self).add_service_args(parser)

        group = parser.add_argument_group("Cloud Service")

        group.add_argument(
            "--credentials",
            help="Path to the credentials files separated by comma or "
            "base64 encoded credentials separated by comma "
            "(or set CLOUD_CREDENTIALS environment variable)",
            type=from_environ("CLOUD_CREDENTIALS"),
            default="",
        )

    def _init_creds(self) -> None:
        """Load the credentials data to memory whenever required."""
        # Note: The credentials list can have a filename or a base64 encoded dict
        credentials = self._service_args.credentials
        credentials = credentials.split(',') if credentials else []
        for cred in credentials:
            if os.path.isfile(cred):  # If it's a filename we load it from JSON
                with open(cred, 'r') as fp:
                    cred_data = json.load(fp)
            else:  # we decode it from base64
                try:
                    b_data = base64.b64decode(cred.encode("ascii"))
                    cred_data = json.loads(b_data.decode("ascii"))
                except Exception as e:
                    message = "Invalid credentials"
                    log.error(f"{message} : {e}")
                    raise ValueError(message) from e

            name = cred_data.get("marketplace_account")
            if not name:
                message = "Missing mandatory key \"marketplace_account\" in credentials."
                log.error(message)
                raise ValueError(message)

            self._creds.update({name: cred_data})

    def _get_cloud_credentials(self, account_name: str) -> MarketplaceAuth:
        """
        Return the credentials for the given account name.

        Args:
            account_name (str)
                The alias of the marketplace to get its account (e.g.: "aws-na").
        Returns:
            dict: The dictionary with the requested marketplace credentials.
        """
        self._init_creds()
        cred = self._creds.get(account_name)
        if not cred:
            message = f"The credentials for {account_name} were not found."
            log.error(message)
            raise ValueError(message)
        return cred

    def cloud_instance(self, account_name: str) -> CloudProvider:
        """
        Return an instance of CloudProvider from the requested account name.

        Args:
            account_name (str)
                The alias of the marketplace to get its account (e.g.: "aws-na").
        """
        with self._lock:
            if account_name not in self._instances:
                creds = self._get_cloud_credentials(account_name)
                instance = get_provider(creds)
                self._instances.update({account_name: instance})
        return self._instances[account_name]
