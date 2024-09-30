from typing import Any, Dict, Set

from pushsource import AmiPushItem, VHDPushItem

CLOUD_NAME_FOR_PI = {
    AmiPushItem: "aws",
    VHDPushItem: "azure",
}


class BuildIdBorg:
    """
    Borg to keep track of single builds with multiple push items.

    Its main goal is to allow tracking when a task was skipped or not for a given
    build which may contain multiple push items for different locations and the mappings are not
    meant for all of them.

    It contains two sets:

    - received_builds: Meant to store the builds from push items received directly from pushsource.
    - processed_builds: Meant to store the builds which were successfully pushed.

    See also: https://baites.github.io/computer-science/patterns/singleton-series/2018/06/11/python-borg-and-the-new-metaborg.html
    """  # noqa: E501

    _shared_state: Dict[str, Any] = {}

    def __new__(cls):
        """Instantiate a new borg object with the shared state."""
        inst = super().__new__(cls)
        inst.__dict__ = cls._shared_state
        return inst

    @property
    def received_builds(self) -> Set[int]:
        """Provide a shared set of received builds."""
        if not hasattr(self, "_received_builds"):
            self._received_builds: Set[int] = set()
        return self._received_builds

    @property
    def processed_builds(self) -> Set[int]:
        """Provide a shared set of processed builds."""
        if not hasattr(self, "_processed_builds"):
            self._processed_builds: Set[int] = set()
        return self._processed_builds
