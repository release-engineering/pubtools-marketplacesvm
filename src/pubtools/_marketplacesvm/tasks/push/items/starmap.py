import logging
from typing import Any, Callable, ClassVar, Dict, List

from attrs import Factory, asdict, define, evolve, field
from attrs.validators import deep_mapping, instance_of
from pushsource import AmiPushItem, AmiRelease, VMIPushItem, VMIRelease
from starmap_client.models import Destination, QueryResponseEntity

log = logging.getLogger("pubtools.marketplacesvm")


@define
class MappedVMIPushItemV2:
    """Wrap a VMIPushItem and its variations with additional information from StArMap (APIv2)."""

    _CONVERTER_HANDLERS: ClassVar[Dict[str, Callable]] = {}

    push_item: VMIPushItem = field(validator=instance_of(VMIPushItem))
    """The underlying pushsource.VMIPushItem."""

    starmap_query_entity: QueryResponseEntity = field(validator=instance_of(QueryResponseEntity))
    """A single QueryResponseEntity from StArMap."""

    _mapped_push_item: Dict[str, VMIPushItem] = field(
        alias="_mapped_push_item",
        default=Factory(dict),
        validator=deep_mapping(
            key_validator=instance_of(str),
            value_validator=instance_of(VMIPushItem),
            mapping_validator=instance_of(dict),
        ),
    )
    """The underlying pushsource.VMIPushItem for each marketplace."""

    @property
    def marketplaces(self) -> List[str]:
        """Return a list of marketplaces accounts for the stored PushItem."""
        return self.starmap_query_entity.account_names

    @property
    def destinations(self) -> List[Destination]:
        """Return a list with all destinations associated with the stored push item."""
        dest = []
        for mkt in self.marketplaces:
            dest.extend(
                [
                    dst
                    for dst in self.starmap_query_entity.mappings[mkt].destinations
                    if not dst.architecture or dst.architecture == self.push_item.release.arch
                ]
            )
        return dest

    @property
    def tags(self) -> Dict[str, Any]:
        """Return all tags associated with the stored push item."""
        res = {}
        for dest in self.destinations:
            if dest.tags:
                res.update(dest.tags)
        return res

    def _update_push_item_properties(
        self, push_item: VMIPushItem, destinations: List[Destination]
    ) -> VMIPushItem:
        """Return an updated push item with data from destinations."""
        # Update the destinations
        pi = evolve(push_item, dest=destinations)

        # Get the "meta" data from destinations
        # Note that this will merge all meta data from every destionation into a single data.
        meta = {}
        for d in destinations:
            if d.meta:
                meta.update(d.meta)

        # Build the VMIRelease information when the meta key `release` is present
        rel_data = meta.get("release", None)
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
                value = meta.get(attribute.name, None)  # Get the value from "dst.meta"
                if value:  # If the value is set in the metadata
                    func = self._CONVERTER_HANDLERS.get(attribute.name, lambda x: x)  # Converter
                    new_attrs.update({attribute.name: func(value)})  # Set the new value
                elif attribute.name not in ignore_unset_attributes:
                    log.warning(
                        "Missing information for the attribute %s.%s, leaving it unset.",
                        pi.name,
                        attribute.name,
                    )

        # Finally return the updated push_item
        return evolve(pi, **new_attrs)

    def _map_push_item(self, destinations: List[Destination]) -> VMIPushItem:
        """Return the wrapped push item with the missing attributes set."""
        if self.push_item.dest:  # If it has destinations it means we already mapped its properties
            # Just update the destinations for the marketplace and return
            self.push_item = evolve(self.push_item, dest=destinations)
            return self.push_item

        # Update the missing fields for push item and its release
        self.push_item = self._update_push_item_properties(self.push_item, destinations)
        return self.push_item

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
        Return a VMIPushItem with the destinations for just a given marketplace account.

        Args:
            account:
                The account alias to retrieve the specific destinations from
        Returns:
            The VMIPushItem with the destinations for the given marketplace account.
        """
        if account not in self.marketplaces:
            raise ValueError(f"No such marketplace {account}")

        if not self._mapped_push_item.get(account):
            destinations = self.starmap_query_entity.mappings[account].destinations
            self._mapped_push_item[account] = self._map_push_item(destinations)

        return self._mapped_push_item.get(account)

    def get_push_item_for_destination(self, destination: Destination) -> VMIPushItem:
        """
        Return a VMIPushItem with all properties updated for a single destination.

        Args:
            destination (Destination): The destination to update the push item.
        """
        return self._update_push_item_properties(self.push_item, [destination])

    def update_push_item_for_marketplace(self, account: str, push_item: VMIPushItem) -> None:
        """Update a push item for a given marketplace account.

        Args:
            account (str): the marketplace account.
            push_item (VMIPushItem): the push item to update with.
        """
        self._mapped_push_item[account] = push_item

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
        destinations = self.starmap_query_entity.mappings[account].destinations
        for dst in destinations:
            if dst.tags:
                res.update(dst.tags)

        return res
