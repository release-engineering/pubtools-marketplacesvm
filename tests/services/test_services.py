# SPDX-License-Identifier: GPL-3.0-or-later
import base64
import json
import logging
import sys
from unittest.mock import MagicMock, patch

import py
import pytest
from _pytest.logging import LogCaptureFixture
from pushcollector._impl.proxy import CollectorProxy
from starmap_client import StarmapClient
from starmap_client.models import QueryResponseContainer, Workflow

from pubtools._marketplacesvm.cloud_providers.ms_azure import AzureProvider
from pubtools._marketplacesvm.services.base import Service
from pubtools._marketplacesvm.tasks.push import MarketplacesVMPush
from tests.utils import load_json


def test_service_args_error() -> None:
    expected_err = "BUG: Service inheritor must provide 'args'"
    with pytest.raises(RuntimeError, match=expected_err):
        Service()._service_args


def test_service_args_success() -> None:
    class FakeService(Service):
        def __init__(self, args):
            self.args = args

    service = FakeService(["args"])
    assert service._service_args == ["args"]


def test_starmap_service() -> None:
    """Ensure the MarketplacesVMPush has a StarmapClient."""
    instance = MarketplacesVMPush()
    arg = ["", "-d", "fakesource"]
    with patch.object(sys, "argv", arg):
        client = instance.starmap
        assert isinstance(client, StarmapClient)
        # Single StarmapClient instance per thread
        assert instance.starmap == client


@patch("pubtools._marketplacesvm.services.starmap.StarmapClient")
def test_starmap_query(mock_client: MagicMock) -> None:
    """Ensure the `StarmapService.query_image_by_name` is properly working."""
    data = load_json("tests/data/starmap/container.json")
    arg = ["", "-d", "fakesource"]

    # Test 1: no mappings loaded: request them from the server
    for i in [list(), data]:
        qrc = QueryResponseContainer.from_json(i)
        mock_client.return_value.query_image_by_name.return_value = qrc
        instance = MarketplacesVMPush()
        with patch.object(sys, "argv", arg):
            res = instance.query_image_by_name("product-test")

        assert res == qrc.responses
        mock_client.return_value.query_image_by_name.assert_called_once_with(
            name="product-test", version=None
        )
        mock_client.reset_mock()

    # Test 2: mappings loaded: should not request from server
    with patch.object(sys, "argv", arg):
        res = instance.query_image_by_name("product-test")

    mock_client.return_value.query_image_by_name.assert_not_called()
    assert res == qrc.responses


@patch("pubtools._marketplacesvm.services.starmap.StarmapClient")
def test_starmap_filter_workflow(mock_client: MagicMock) -> None:
    """Ensure the `StarmapService.filter_by_workflow` are properly working."""
    data = load_json("tests/data/starmap/container.json")
    qrc = QueryResponseContainer.from_json(data)
    mock_client.return_value.query_image_by_name.return_value = qrc
    arg = ["", "-d", "fakesource"]
    expected = qrc.responses[1]

    instance = MarketplacesVMPush()
    with patch.object(sys, "argv", arg):
        q = instance.query_image_by_name("product-test")
        res = instance.filter_for(q, workflow=Workflow.community)

    assert res == [expected]


@patch("pubtools._marketplacesvm.services.starmap.StarmapClient")
def test_starmap_unknown_format_exception(mock_client: MagicMock) -> None:
    """Ensure the `StarmapService.filter_by_workflow` are properly working."""
    mock_client.return_value.query_image_by_name.return_value = {"foo": "bar"}
    arg = ["", "-d", "fakesource"]
    instance = MarketplacesVMPush()
    err = "Unknown response format from StArMap: <class 'dict'>"
    with patch.object(sys, "argv", arg):
        with pytest.raises(RuntimeError, match=err):
            instance.query_image_by_name("product-test")


def test_collector_service() -> None:
    """Ensure the MarketplaceVMPush has a Collector service."""
    instance = MarketplacesVMPush()
    arg = ["", "-d", "fakesource"]
    with patch.object(sys, "argv", arg):
        collector = instance.collector
        assert isinstance(collector, CollectorProxy)
        # Single CollectorProxy instance per thread
        assert instance.collector == collector


@patch("pubtools._marketplacesvm.cloud_providers.ms_azure.AzureUploadMetadata")
@patch("pubtools._marketplacesvm.cloud_providers.ms_azure.AzureUploadService")
@patch("pubtools._marketplacesvm.cloud_providers.ms_azure.AzurePublishMetadata")
@patch("pubtools._marketplacesvm.cloud_providers.ms_azure.AzurePublishService")
def test_azure_provider_service(
    mock_ps: MagicMock,
    mock_pm: MagicMock,
    mock_us: MagicMock,
    mock_um: MagicMock,
    tmpdir: py.path.local,
    caplog: LogCaptureFixture,
) -> None:
    """Ensure the MarketplaceVMPush has a AzureProvider service."""
    fake_auth = {
        "marketplace_account": "azure-na",
        "auth": {
            "AZURE_PUBLISHER_NAME": "publisher_name",
            "AZURE_TENANT_ID": "tenant_id",
            "AZURE_CLIENT_ID": "client_id",
            "AZURE_API_SECRET": "api_secret",
            "AZURE_STORAGE_CONNECTION_STRING": "conn_str",
        },
    }

    # For testing with credentials from file
    creds_file = tmpdir.join("auth.json")
    with open(creds_file, 'w') as f:
        f.write(json.dumps(fake_auth, indent=2))

    # For testing with credentials from Base64
    auth_data = json.dumps(fake_auth).encode('ascii')
    b_data = base64.b64encode(auth_data)

    # Test valid credentials (from file and base64)
    creds = [str(creds_file), b_data.decode('ascii')]
    for cred in creds:
        instance = MarketplacesVMPush()
        arg = ["", "--credentials", cred, "-d", "-d", "fakesource"]
        with patch.object(sys, "argv", arg):
            provider = instance.cloud_instance("azure-na")
            assert isinstance(provider, AzureProvider)
            # Single AzureProvider instance per thread
            assert instance.cloud_instance("azure-na") == provider

    # Test allow draft push
    with patch("pubtools._marketplacesvm.services.cloud.get_provider") as mock_getprvdr:
        instance = MarketplacesVMPush()
        arg = ["", "--credentials", str(creds_file), "--azure-allow-draft-push", "fakesource"]
        with patch.object(sys, "argv", arg):
            provider = instance.cloud_instance("azure-na")
            mock_getprvdr.assert_called_once_with(fake_auth, allow_draft_push=True)

    # Test invalidcredentials
    with caplog.at_level(logging.INFO):
        with pytest.raises(ValueError, match="Invalid credentials"):
            instance = MarketplacesVMPush()
            arg = ["", "--credentials", "invalid_credentials", "-d", "-d", "fakesource"]
            with patch.object(sys, "argv", arg):
                instance.cloud_instance("azure-emea")

    # Test non-existent cloud
    with caplog.at_level(logging.INFO):
        with pytest.raises(ValueError, match="The credentials for azure-emea were not found."):
            instance = MarketplacesVMPush()
            arg = ["", "--credentials", str(creds_file), "-d", "-d", "fakesource"]
            with patch.object(sys, "argv", arg):
                instance.cloud_instance("azure-emea")

    # Test missing marketplace name
    fake_auth.pop("marketplace_account")
    with open(creds_file, 'w') as f:
        f.write(json.dumps(fake_auth, indent=2))

    expected_err = "Missing mandatory key \"marketplace_account\" in credentials."
    with caplog.at_level(logging.INFO):
        with pytest.raises(ValueError, match=expected_err):
            instance = MarketplacesVMPush()
            arg = ["", "--credentials", str(creds_file), "-d", "-d", "fakesource"]
            with patch.object(sys, "argv", arg):
                instance.cloud_instance("azure-emea")

    mock_ps.assert_called()
    mock_us.from_connection_string.assert_called()
    mock_pm.assert_not_called()
    mock_um.assert_not_called()
