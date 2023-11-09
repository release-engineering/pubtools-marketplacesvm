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
from datetime import datetime
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
