import logging
from typing import Any, Callable, ClassVar, Dict, List

from attrs import define, evolve, field
from attrs.validators import deep_mapping, instance_of
from pushsource import VMIPushItem
from starmap_client.models import Destination

log = logging.getLogger("pubtools.marketplacesvm")


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
    def push_item(self) -> VMIPushItem:
        """Return the wrapped push item with the missing attributes set."""
        if self._push_item.dest:  # If it has destinations it means we already mapped it
            return self._push_item

        # Update the missing fields for push item and its release
        pi = self._push_item

        # Update the destinations
        pi = evolve(pi, dest=self.destinations)

        # Update the push item attributes for each type using the attrs hidden annotation
        ignore_unset_attributes = ["md5sum", "sha256sum", "signing_key", "origin"]
        new_attrs = {}
        for attribute in pi.__attrs_attrs__:
            if not getattr(pi, attribute.name, None):  # If attribute is not set
                value = self.meta.get(attribute.name, None)  # Get the value from "dst.meta"
                if value:  # If the value is set in the metadata
                    value = self._CONVERTER_HANDLERS.get(attribute.name, value)  # Value conversion
                    new_attrs.update({attribute.name: value})  # Set the new value
                elif attribute.name not in ignore_unset_attributes:
                    log.warning(
                        "Missing information for the attribute %s.%s, leaving it unset.",
                        self._push_item.name,
                        attribute.name,
                    )

        # Finally return the updated push_item
        self._push_item = evolve(pi, **new_attrs)
        return self._push_item

    @push_item.setter
    def push_item(self, x: VMIPushItem) -> None:
        self._push_item = x

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
        push_item = self.push_item
        return evolve(push_item, dest=destinations)

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
