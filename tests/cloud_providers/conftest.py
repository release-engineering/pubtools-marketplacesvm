# SPDX-License-Identifier: GPL-3.0-or-later
from typing import Any, Dict, Optional, Tuple, TypeVar

import pytest

from pubtools._marketplacesvm.cloud_providers import CloudProvider

T = TypeVar('T')


class FakeProvider(CloudProvider):
    def __init__(self, creds) -> None:
        pass

    @classmethod
    def from_credentials(cls, fake_creds: Dict[str, Any]) -> 'FakeProvider':
        return cls(fake_creds)

    def _upload(
        self, push_item: T, custom_tags: Optional[Dict[str, str]] = None, **kwargs
    ) -> Tuple[T, Any]:
        return push_item, True

    def _pre_publish(self, push_item, **kwargs):
        return push_item, kwargs

    def _publish(
        self,
        push_item: T,
        nochannel: bool,
        overwrite: bool = False,
        **kwargs,
    ) -> Tuple[T, Any]:
        return push_item, True

    def _delete_push_images(self, push_item, **kwargs):
        return push_item


@pytest.fixture
def fake_provider():
    yield FakeProvider.from_credentials({})
