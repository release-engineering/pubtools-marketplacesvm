# SPDX-License-Identifier: GPL-3.0-or-later
from typing import Any, TypeVar

import pytest

from pubtools._marketplacesvm.cloud_providers import CloudProvider

T = TypeVar('T')


class FakeProvider(CloudProvider):
    def from_credentials(self):
        pass

    def _upload(self, push_item: T) -> Any:
        pass

    def _publish(self, push_item: T, nochannel: bool, overwrite: bool = False) -> Any:
        pass


@pytest.fixture
def fake_provider():
    yield FakeProvider()
