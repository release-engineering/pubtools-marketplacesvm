# SPDX-License-Identifier: GPL-3.0-or-later
import logging

import pytest
from _pytest.logging import LogCaptureFixture
from pushsource import PushItem

from pubtools._marketplacesvm.cloud_providers import CloudCredentials, CloudProvider, get_provider

from .conftest import FakeProvider


def test_get_provider_invalid(caplog: LogCaptureFixture) -> None:
    expected_err = "Missing or invalid credentials."
    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError, match=expected_err):
            get_provider({"marketplace_account": "foo", "auth": {}})


def test_get_provider_notfound(caplog: LogCaptureFixture) -> None:
    expected_err = "No provider found for cloud-emea"
    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError, match=expected_err):
            get_provider({"marketplace_account": "cloud-emea", "auth": {"auth": "data"}})


class TestCloudCredentials:
    def test_invalid_credentials(self) -> None:
        """Ensure the `cloud_name` must contain the prefix `-na` or `-emea`."""
        expected_err = "Invalid value for cloud_name: missing region."
        with pytest.raises(ValueError, match=expected_err):
            CloudCredentials(cloud_name="foo")

        assert CloudCredentials(cloud_name="foo-na")
        assert CloudCredentials(cloud_name="foo-emea")
        assert CloudCredentials(cloud_name="foo-storage")


class TestCloudProvider:
    def test_abstract_class(self) -> None:
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            CloudProvider()  # type: ignore

    def test_raise_error_with_logs(self, caplog: LogCaptureFixture) -> None:
        message = "something bad happended"
        with caplog.at_level(logging.ERROR):
            with pytest.raises(ValueError, match=message):
                CloudProvider.raise_error(ValueError, message)
        assert message in caplog.text

    def test_default_post_actions(self, fake_provider: FakeProvider) -> None:
        """Test the default behavior for `_post_upload` and `_post_publish`."""
        push_item = PushItem(name="test")

        assert (push_item, "Upload") == fake_provider._post_upload(push_item, "Upload")
        assert (push_item, "Publish") == fake_provider._post_publish(push_item, "Publish")
