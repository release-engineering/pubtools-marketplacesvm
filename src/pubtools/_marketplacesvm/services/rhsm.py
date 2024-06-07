# SPDX-License-Identifier: GPL-3.0-or-later
#
# This file was based on:
#   https://github.com/release-engineering/pubtools-ami/blob/main/pubtools/_ami/rhsm.py
#
import logging
import os
import sys
import threading
from argparse import ArgumentParser
from concurrent.futures import Future
from datetime import datetime, timezone
from typing import Any, Generic, NoReturn, Optional, Set, TypeVar
from urllib.parse import urljoin

import requests
from more_executors import Executors
from more_executors.futures import f_map
from pubtools.pluggy import pm

from ..arguments import from_environ
from .base import Service

T = TypeVar("T")

if sys.version_info < (3, 9):

    class FutureType(Generic[T]):  # noqa: D101  pragma: no cover
        def set_exception(self, exc_info: BaseException) -> None:  # noqa: D102
            ...  # pragma: no cover

        def set_result(self, result: Any) -> None:  # noqa: D102  pragma: no cover
            ...  # pragma: no cover

else:
    FutureType = Future  # pragma: no cover

LOG = logging.getLogger("pubtools.marketplacesvm")


class RHSMClient:
    """Client for RHSM updates."""

    _RHSM_REQUEST_THREADS = int(os.environ.get("RHSM_REQUEST_THREADS", "4"))

    def __init__(self, url: str, max_retry_sleep: Optional[float] = None, **kwargs):
        """Create a new RHSM client.

        Args:
            ulr(str)
                Base URL of the RHSM API.
            max_retry_sleep (float, optional)
                Max number of seconds to sleep between retries.
                Mainly provided so that tests can reduce the time needed to retry.
            kwargs
                Remaining arguments are used to initialize the requests.Session()
                used within this class (e.g. "verify", "auth").
        """
        self._url = url
        self._tls = threading.local()

        retry_args = {}
        if max_retry_sleep:
            retry_args["max_sleep"] = max_retry_sleep

        self._session_attrs = kwargs
        self._executor = Executors.thread_pool(
            name="rhsm-client", max_workers=self._RHSM_REQUEST_THREADS
        ).with_retry(**retry_args)

    @staticmethod
    def _check_http_response(response: requests.Response) -> requests.Response:
        response.raise_for_status()
        return response

    @property
    def _session(self) -> requests.Session:
        if not hasattr(self._tls, "session"):
            self._tls.session = requests.Session()
            for key, value in self._session_attrs.items():
                setattr(self._tls.session, key, value)
        return self._tls.session

    def _on_failure(self, exception: Exception) -> NoReturn:
        LOG.error("Failed to process request to RHSM with exception %s", exception)
        raise exception

    def _get(self, *args, **kwargs) -> requests.Response:
        return self._session.get(*args, **kwargs)

    def _send(self, prepped_req: requests.PreparedRequest, **kwargs) -> requests.Response:
        settings = {
            "url": prepped_req.url,
            "proxies": kwargs.get("proxies"),
            "stream": kwargs.get("stream"),
            "verify": kwargs.get("verify"),
            "cert": kwargs.get("cert"),
        }
        # merging environment settings because prepared request doesn't take them into account
        # details: https://requests.readthedocs.io/en/latest/user/advanced/#prepared-requests
        merged = self._session.merge_environment_settings(**settings)  # type: ignore [arg-type]
        kwargs.update(merged)
        return self._session.send(prepped_req, **kwargs)


class AwsRHSMClient(RHSMClient):
    """Client for RHSM management with AWS content."""

    AMIS_URL = "/v1/internal/cloud_access_providers/amazon/amis"

    def aws_products(self) -> FutureType[requests.Response]:
        """Return the list of AWS products present in RHSM.

        Returns:
            Future[requests.Response]: the AWS products list from RHSM server.
        """
        url = urljoin(
            self._url,
            "/v1/internal/cloud_access_providers/amazon/provider_image_groups",
        )
        LOG.debug("Fetching product from %s", url)

        out = self._executor.submit(self._get, url)
        out = f_map(out, fn=self._check_http_response, error_fn=self._on_failure)

        return out

    def aws_create_region(
        self, region: str, aws_provider_name: str
    ) -> FutureType[requests.Response]:
        """Create a new AWS region in RHSM.

        Args:
            region (str): The region name to create
            aws_provider_name (str): The AWS provider name

        Returns:
            Future[requests.Response]: The RHSM server result operation.
        """
        url = urljoin(self._url, "v1/internal/cloud_access_providers/amazon/regions")

        rhsm_region = {"regionID": region, "providerShortname": aws_provider_name}
        req = requests.Request("POST", url, json=rhsm_region)
        prepped_req = self._session.prepare_request(req)

        out = self._executor.submit(self._send, prepped_req)
        out = f_map(out, error_fn=self._on_failure)

        return out

    def aws_update_image(
        self,
        image_id: str,
        image_name: str,
        arch: str,
        product_name: str,
        version: Optional[str] = None,
        variant: Optional[str] = None,
        status: str = "VISIBLE",
    ) -> FutureType[requests.Response]:
        """Update an AMI in RHSM.

        Args:
            image_id (str): The AMI ID
            image_name (str): The image name
            arch (str): The AMI architecture
            product_name (str): The product name
            version (Optional[str], optional): The product version. Defaults to None.
            variant (Optional[str], optional): The product variant, if any. Defaults to None.
            status (str, optional): The product status. Defaults to "VISIBLE".

        Returns:
            Future[requests.Response]: The RHSM server result operation.
        """
        url = urljoin(self._url, self.AMIS_URL)

        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        rhsm_image = {
            "amiID": image_id,
            "arch": arch.lower(),
            "product": product_name,
            "version": version or "none",
            "variant": variant or "none",
            "description": "Released %s on %s" % (image_name, now),
            "status": status,
        }
        req = requests.Request("PUT", url, json=rhsm_image)
        prepped_req = self._session.prepare_request(req)

        out = self._executor.submit(self._send, prepped_req)
        out = f_map(out, error_fn=self._on_failure)

        return out

    def aws_create_image(
        self,
        image_id: str,
        image_name: str,
        arch: str,
        product_name: str,
        region: str,
        version: Optional[str] = None,
        variant: Optional[str] = None,
    ) -> FutureType[requests.Response]:
        """Create an AMI in RSHM server.

        Args:
            image_id (str): The AMI ID
            image_name (str): The image name
            arch (str): The AMI architecture
            product_name (str): The product name
            region (str): The AWS region
            version (Optional[str], optional): The product version. Defaults to None.
            variant (Optional[str], optional): The product variant, if any. Defaults to None.

        Returns:
            Future[requests.Response]: The RHSM server result operation.
        """
        url = urljoin(self._url, self.AMIS_URL)

        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        rhsm_image = {
            "amiID": image_id,
            "region": region,
            "arch": arch.lower(),
            "product": product_name,
            "version": version or "none",
            "variant": variant or "none",
            "description": "Released %s on %s" % (image_name, now),
            "status": "VISIBLE",
        }
        req = requests.Request("POST", url, json=rhsm_image)
        prepped_req = self._session.prepare_request(req)

        out = self._executor.submit(self._send, prepped_req)
        out = f_map(out, error_fn=self._on_failure)

        return out

    def aws_list_image_ids(self) -> Set[str]:
        """Return all AMI IDs present in RHSM.

        Returns:
            Set[str]: Set containing all AMI IDs in RHSM.
        """
        url = urljoin(self._url, self.AMIS_URL)
        image_ids = set()

        def handle_page(offset: int = 0):
            params = {"limit": 1000, "offset": offset}
            req = requests.Request("GET", url, params=params)
            prepped_req = self._session.prepare_request(req)

            resp_f = self._executor.submit(self._send, prepped_req)
            resp_f = f_map(resp_f, fn=self._check_http_response, error_fn=self._on_failure)
            resp = resp_f.result().json()
            items_count = resp["pagination"]["count"]
            if items_count:
                offset += items_count
                for item in resp.get("body") or []:
                    image_ids.add(item["amiID"])
                return handle_page(offset)

        LOG.debug("Listing all images from rhsm, %s", url)
        handle_page()
        return image_ids


class AwsRHSMClientService(Service):
    """A service providing RHSM client for AWS.

    A client will be available only when RHSM url is provided.
    """

    def __init__(self, *args, **kwargs):
        """Initialize the AwsRHSMClientService."""
        self._lock = threading.Lock()
        self._rhsm_instance = None
        super(AwsRHSMClientService, self).__init__(*args, **kwargs)

    def add_service_args(self, parser: ArgumentParser) -> None:
        """Include the required arguments for the RHSM service.

        Args:
            parser (_type_): The parser to include the additional arguments.
        """
        super(AwsRHSMClientService, self).add_service_args(parser)

        group = parser.add_argument_group("RHSM service")

        group.add_argument("--rhsm-url", help="Base URL of the RHSM API")
        group.add_argument(
            "--rhsm-cert",
            help="RHSM API certificate path (or set RHSM_CERT environment variable)",
            type=from_environ("RHSM_CERT"),
        )
        group.add_argument(
            "--rhsm-key",
            help="RHSM API key path (or set RHSM_KEY environment variable)",
            type=from_environ("RHSM_KEY"),
        )

    @property
    def rhsm_client(self) -> 'AwsRHSMClient':
        """RHSM client used for AMI related info on RHSM.

        Error will be raised if the URL is not provided in the CLI.
        """
        with self._lock:
            if not self._rhsm_instance:
                self._rhsm_instance = self._get_rhsm_instance()
        return self._rhsm_instance

    def _get_rhsm_instance(self) -> 'AwsRHSMClient':
        rhsm_url = self._service_args.rhsm_url
        rhsm_cert = self._service_args.rhsm_cert
        rhsm_key = self._service_args.rhsm_key
        if not rhsm_url:
            raise ValueError("RHSM URL not provided for the RHSM client")

        result = pm.hook.get_cert_key_paths(server_url=rhsm_url)  # pylint: disable=no-member
        default_cert, default_key = result if result else (None, None)
        cert = rhsm_cert or default_cert, rhsm_key or default_key
        return AwsRHSMClient(rhsm_url, cert=cert)
