import logging
from typing import Any, Callable, ClassVar, Dict, List

from attrs import asdict, define, evolve, field
from attrs.validators import deep_mapping, instance_of
from pushsource import AmiPushItem, AmiRelease, VMIPushItem, VMIRelease
from starmap_client.models import Destination

log = logging.getLogger("pubtools.marketplacesvm")


def has_destination_stage_preview(destinations: List[Destination]) -> bool:
    """Return True when one or more destinations is marked with `stage_preview` as `True`.

    Args:
        destinations
            List of destinations to check whether one or more of them has `stage_preview` set
            as `True`
    """
    res = False
    for dst in destinations:
        res = res or dst.stage_preview
    return res


@define
class MappedVMIPushItem:
    """Wrap a VMIPushItem and its variations with additional information from StArMap."""

    _CONVERTER_HANDLERS: ClassVar[Dict[str, Callable]] = {}

    _push_item: VMIPushItem = field(alias="_push_item", validator=instance_of(VMIPushItem))
    """The underlying pushsource.VMIPushItem."""

    clouds: Dict[str, List[Destination]] = field(
        validator=deep_mapping(
            key_validator=instance_of(str),
            value_validator=instance_of(list),
            mapping_validator=instance_of(dict),
        )
    )
    """Dictionary with the marketplace accounts and its destinations."""

    @property
    def state(self) -> str:
        """Get the wrapped push item state."""
        return self._push_item.state

    @state.setter
    def state(self, state: str) -> None:
        if not isinstance(state, str):
            raise TypeError(f"Expected to receive a string for state, got: {type(state)}")
        self._push_item = evolve(self._push_item, state=state)

    @property
    def marketplaces(self) -> List[str]:
        """Return a list of marketplaces accounts for the stored PushItem."""
        return list(self.clouds.keys())

    @property
    def destinations(self) -> List[Destination]:
        """Return a list with all destinations associated with the stored push item."""
        dest = []
        for mkt in self.marketplaces:
            dest.extend(
                [
                    dst
                    for dst in self.clouds[mkt]
                    if not dst.architecture or dst.architecture == self._push_item.release.arch
                ]
            )
        return dest

    @property
    def meta(self) -> Dict[str, Any]:
        """Return all metadata associated with the stored push item."""
        res = {}
        for dest in self.destinations:
            if dest.meta:
                res.update({k: v for k, v in dest.meta.items()})
        return res

    @property
    def tags(self) -> Dict[str, Any]:
        """Return all tags associated with the stored push item."""
        res = {}
        for dest in self.destinations:
            if dest.tags:
                res.update(dest.tags)
        return res

    def _map_push_item(self, destinations: List[Destination]) -> VMIPushItem:
        """Return the wrapped push item with the missing attributes set."""
        if self._push_item.dest:  # If it has destinations it means we already mapped its properties
            # Just update the destinations for the marketplace and return
            self.push_item = evolve(self._push_item, dest=destinations)
            return self._push_item

        # Update the missing fields for push item and its release
        pi = self._push_item

        # Update the destinations
        pi = evolve(pi, dest=destinations)

        # Build the VMIRelease information when the meta key `release` is present
        rel_data = self.meta.pop("release", None)
        if rel_data:
            if pi.release:
                log.debug("Merging original release information with data from StArMap")
                # We just want to set the values present in StArMap and preserve what's given by
                # the original "pi.release" when the attribute is NOT set by StArMap
                old_release_data = asdict(pi.release)
                old_release_data.update(rel_data)
                rel_data = old_release_data
            log.debug("Creating a VMIRelease object with %s", rel_data)
            rel_obj = (
                AmiRelease(**rel_data) if isinstance(pi, AmiPushItem) else VMIRelease(**rel_data)
            )
            pi = evolve(pi, release=rel_obj)

        # Update the push item attributes for each type using the attrs hidden annotation
        ignore_unset_attributes = ["md5sum", "sha256sum", "signing_key", "origin"]
        new_attrs = {}
        for attribute in pi.__attrs_attrs__:
            if not getattr(pi, attribute.name, None):  # If attribute is not set
                value = self.meta.get(attribute.name, None)  # Get the value from "dst.meta"
                if value:  # If the value is set in the metadata
                    func = self._CONVERTER_HANDLERS.get(attribute.name, lambda x: x)  # Converter
                    new_attrs.update({attribute.name: func(value)})  # Set the new value
                elif attribute.name not in ignore_unset_attributes:
                    log.warning(
                        "Missing information for the attribute %s.%s, leaving it unset.",
                        self._push_item.name,
                        attribute.name,
                    )

        # Finally return the updated push_item
        self._push_item = evolve(pi, **new_attrs)
        return self._push_item

    def _set_push_item(self, pi: VMIPushItem) -> None:
        """Update the internal push item with the given one."""
        self._push_item = pi

    # The property "push_item" is only setter since the getter
    # needs to be used as `get_push_item_for_marketplace`.
    push_item = property(None, _set_push_item)

    @classmethod
    def register_converter(cls, name: str, func: Callable) -> None:
        """
        Register a specialized attribute converter for the inner push item.

        Args:
            name
                The attribute name to be processed by the callable.
            func
                The callable to be used as converter
        """
        cls._CONVERTER_HANDLERS.update({name: func})

    def get_push_item_for_marketplace(self, account: str) -> VMIPushItem:
        """
        Return a VMIPushItem with the destinations for just a given marketplace acconut.

        Args:
            account:
                The account alias to retrieve the specific destinations from
        Returns:
            The VMIPushItem with the destinations for the given marketplace account.
        """
        if account not in self.marketplaces:
            raise ValueError(f"No such marketplace {account}")

        destinations = self.clouds[account]
        return self._map_push_item(destinations)

    def get_metadata_for_mapped_item(self, destination: Destination) -> Dict[str, Any]:
        """
        Return all metadata related to a push item containing a single destination.

        Args:
            destination
                A single Destination to obtain the related metadata.
        Returns:
            The related metadata for the given destination.
        """
        for dst in self.destinations:
            if dst == destination:
                return dst.meta
        return {}

    def get_tags_for_mapped_item(self, destination: Destination) -> Dict[str, str]:
        """Return all custom tags related to a push item containing a single destination.

        Args:
            destination
                A single Destination to obtain the related custom tags.
        Returns:
            The related custom tags for the given destination.
        """
        for dst in self.destinations:
            if dst == destination:
                return dst.tags
        return {}

    def get_tags_for_marketplace(self, account: str) -> Dict[str, str]:
        """Return all custom tags for the destinations of a given marketplace account.

        Args:
            account (str): The account alias to retrieve the tags from

        Returns:
            Dict[str, str]: The custom tags for the destinations of the given marketplace account.
        """
        if account not in self.marketplaces:
            raise ValueError(f"No such marketplace {account}")

        res = {}
        destinations = self.clouds[account]
        for dst in destinations:
            if dst.tags:
                res.update(dst.tags)

        return res
