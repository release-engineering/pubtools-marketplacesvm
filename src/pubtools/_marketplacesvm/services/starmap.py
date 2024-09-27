import logging
import threading
from argparse import ArgumentParser
from typing import Any, Dict, List, Optional

from starmap_client import StarmapClient
from starmap_client.models import QueryResponseContainer, QueryResponseEntity
from starmap_client.providers import InMemoryMapProviderV2
from starmap_client.session import StarmapMockSession, StarmapSession

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
        self._container = None
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
            "[{'aws-na': {'destinations' [{'destination': 'c39fd...'}, ...]},...},...}]",
            type=str,
            default=[],
            action=RepoQueryLoad,
        )

        group.add_argument(
            "--offline",
            help="Do not connect to a real StArMap server, use a mock session instead. "
            "It requires --repo to be set.",
            action='store_true',
        )

    def _get_repo(self) -> Dict[str, Any]:
        """Instantiate the InMemoryMapProvider when ``--repo`` is passed.

        This will make starmap_client load the list of mappings from memory
        first and only call the server whenever the local mapping is not found.
        """
        local_mappings = self._service_args.repo
        if local_mappings:
            self._container = QueryResponseContainer.from_json(local_mappings)
            provider = InMemoryMapProviderV2(container=self._container)
            return {"provider": provider}
        elif self._service_args.offline is True:
            self.parser.error("Cannot use \"--offline\" without defining \"--repo\" mappings.")  # type: ignore [attr-defined]  # noqa: E501
        return {}

    @property
    def starmap(self) -> StarmapClient:
        """Return a StArMap Client instance."""
        with self._lock:
            if not self._instance:
                offline = self._service_args.offline
                kwargs = self._get_repo()
                session_klass = StarmapSession if not offline else StarmapMockSession
                session = session_klass(self._service_args.starmap_url, api_version="v2")
                self._instance = StarmapClient(session=session, **kwargs)
        return self._instance

    def _store_container_responses(self, qrc: QueryResponseContainer) -> None:
        for qre in qrc.responses:
            if qre not in self._container.responses:  # type: ignore [attr-defined]
                self._container.responses.append(qre)  # type: ignore [attr-defined]

    def _query_server(self, name: str, version: Optional[str]) -> List[QueryResponseEntity]:
        qrc = self.starmap.query_image_by_name(name=name, version=version)
        if not qrc:
            return []
        if not isinstance(qrc, QueryResponseContainer):
            raise RuntimeError(f"Unknown response format from StArMap: {type(qrc)}")

        self._container = self._container or qrc
        with self._lock:
            self._store_container_responses(qrc)
        return qrc.responses

    def query_image_by_name(
        self, name: str, version: Optional[str] = None
    ) -> List[QueryResponseEntity]:
        """Perform a query to StArMap whenever necessary.

        It will use the internaly stored container for filtering whenever a mapping matches it.

        This prevents unecessary calls to the server, acting like a cache for it.

        Args:
            name (str):
                The image name to query
            version (str, optional):
                The version to match the destinations.
        Returns:
            List[QueryResponseEntity]: The requested data when found or an empty list.
        """
        if self._container:
            return self._container.filter_by_name(name) or self._query_server(name, version)
        return self._query_server(name, version)

    @staticmethod
    def filter_for(
        responses: List[QueryResponseEntity],
        **kwargs,
    ) -> List[QueryResponseEntity]:
        """Filter a list of responses using the requested parameters.

        Args:
            responses (list):
                A list of responses from StArMap APIv2.
            kwargs:
                The filter parameters to select the list data
        Returns:
            List[QueryResponseEntity]: List with filtered data for the requested criteria.
        """
        qrc = QueryResponseContainer(responses)
        return qrc.filter_by(**kwargs)
