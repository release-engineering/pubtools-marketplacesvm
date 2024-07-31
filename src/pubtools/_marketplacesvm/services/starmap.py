import logging
import threading
from argparse import ArgumentParser
from typing import Any, Dict

from starmap_client import StarmapClient
from starmap_client.providers import InMemoryMapProvider

from ..arguments import RepoQueryLoad
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

        group.add_argument(
            "--repo",
            help="Override the StArMap mappings for push items. "
            "e.g: {'name': 'foo', 'workflow': 'stratosphere': "
            "{'aws-na': [{'destination': 'c39fd...'}, ...]},...}",
            type=str,
            default={},
            action=RepoQueryLoad,
        )

    def _get_repo(self) -> Dict[str, Any]:
        """Instantiate the InMemoryMapProvider when ``--repo`` is passed.

        This will make starmap_client load the list of mappings from memory
        first and only call the server whenever the local mapping is not found.
        """
        local_mappings = self._service_args.repo
        if local_mappings:
            provider = InMemoryMapProvider(local_mappings)
            return {"provider": provider}
        return {}

    @property
    def starmap(self) -> StarmapClient:
        """Return a StArMap Client instance."""
        with self._lock:
            if not self._instance:
                kwargs = self._get_repo()
                self._instance = StarmapClient(self._service_args.starmap_url, **kwargs)
        return self._instance
