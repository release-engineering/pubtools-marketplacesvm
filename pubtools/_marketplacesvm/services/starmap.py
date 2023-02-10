import logging
import threading
from argparse import ArgumentParser

from starmap_client import StarmapClient

from .base import Service

log = logging.getLogger("pubtools.marketplacesvm")


class StarmapService(Service):
    """
    Define the service for communicating with StArMap.

    The service client is returned when the ``starmap_url`` is provided.
    """

    def __init__(self, *args, **kwargs) -> None:
        """Instantiate a StarmapService object."""
        self._instance = None
        self._lock = threading.Lock()
        super(StarmapService, self).__init__(*args, **kwargs)

    def add_service_args(self, parser: ArgumentParser) -> None:
        """
        Add the required CLI arguments for StarmapService.

        Args:
            parser (ArgumentParser)
                The parser to include the additional arguments.
        """
        super(StarmapService, self).add_service_args(parser)

        group = parser.add_argument_group("StArMap Service")

        group.add_argument(
            "--starmap-url",
            help="Base URL for the StArMap server.",
            type=str,
            default="https://starmap.engineering.redhat.com",
        )

    @property
    def starmap(self) -> StarmapClient:
        """Return a StArMap Client instance."""
        with self._lock:
            if not self._instance:
                self._instance = StarmapClient(self._service_args.starmap_url)
        return self._instance
