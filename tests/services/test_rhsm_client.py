# SPDX-License-Identifier: GPL-3.0-or-later
# This file was based on:
#   https://github.com/release-engineering/pubtools-ami/blob/main/tests/rhsm/test_rhsm_client.py
#
import logging

from _pytest.logging import LogCaptureFixture
from mock import patch
from requests.exceptions import ConnectionError

from pubtools._marketplacesvm.services.rhsm import AwsRHSMClient


def test_rhsm_products(requests_mocker) -> None:
    """Check the api to get the products available for each provider type in RHSM."""
    url = "https://example.com/v1/internal/cloud_access_providers/amazon/provider_image_groups"
    products = {
        "body": [
            {"name": "RHEL", "providerShortName": "awstest"},
            {"name": "RHEL_HOURLY", "providerShortName": "awstest"},
        ]
    }
    requests_mocker.register_uri("GET", url, [{"json": products}, {"status_code": 500}])

    client = AwsRHSMClient("https://example.com", cert=("client.crt", "client.key"))

    out = client.aws_products()
    out = out.result().json()
    assert out == products

    exception = client.aws_products().exception()
    assert "500 Server Error" in str(exception)


def test_create_region(requests_mocker) -> None:
    """Check the api to create region of AWS provider on RHSM for success and failure."""
    url = "https://example.com/v1/internal/cloud_access_providers/amazon/regions"
    m_create_region = requests_mocker.register_uri(
        "POST", url, [{"status_code": 200}, {"status_code": 500}]
    )

    expected_region_req = {"regionID": "us-east-1", "providerShortname": "AWS"}

    client = AwsRHSMClient("https://example.com", cert=("client.crt", "client.key"))

    out = client.aws_create_region("us-east-1", "AWS")
    assert out.result().ok
    assert m_create_region.call_count == 1
    assert m_create_region.last_request.json() == expected_region_req

    out = client.aws_create_region("us-east-1", "AWS")
    assert not out.result().ok
    assert m_create_region.call_count == 2


def test_update_image(requests_mocker, caplog: LogCaptureFixture) -> None:
    """Check the api that updates the AMI metadata present on RHSM for a specifc AMI ID."""
    url = "https://example.com/v1/internal/cloud_access_providers/amazon/amis"
    m_update_image = requests_mocker.register_uri(
        "PUT",
        url,
        [{"status_code": 200}, {"status_code": 500}, {"exc": ConnectionError}],
    )
    caplog.set_level(logging.INFO)
    date_now = "2020-10-29T09:03:55"
    expected_update_img_req = {
        "status": "VISIBLE",
        "amiID": "ami-123",
        "product": "RHEL",
        "description": "Released ami-rhel on 2020-10-29T09:03:55",
        "variant": "Server",
        "version": "7.3",
        "arch": "x86_64",
    }

    client = AwsRHSMClient(
        "https://example.com", cert=("client.crt", "client.key"), max_retry_sleep=0.001
    )
    with patch("pubtools._marketplacesvm.services.rhsm.datetime") as now:
        now.now().replace().isoformat.return_value = date_now
        out = client.aws_update_image(
            "ami-123", "ami-rhel", "x86_64", "RHEL", version="7.3", variant="Server"
        )
    assert out.result().ok
    assert m_update_image.call_count == 1
    assert m_update_image.last_request.json() == expected_update_img_req

    out = client.aws_update_image(
        "ami-123", "ami-rhel", "x86_64", "RHEL", version="7.3", variant="Server"
    )
    assert not out.result().ok
    assert m_update_image.call_count == 2

    out = client.aws_update_image(
        "ami-123", "ami-rhel", "x86_64", "RHEL", version="7.3", variant="Server"
    )
    assert isinstance(out.exception(), ConnectionError)
    assert caplog.messages == ["Failed to process request to RHSM with exception "]


def test_create_image(requests_mocker, caplog: LogCaptureFixture) -> None:
    """Check the api that creates the AMI metadata on RHSM."""
    url = "https://example.com/v1/internal/cloud_access_providers/amazon/amis"
    m_create_image = requests_mocker.register_uri(
        "POST",
        url,
        [{"status_code": 200}, {"status_code": 500}, {"exc": ConnectionError}],
    )
    caplog.set_level(logging.INFO)
    date_now = "2020-10-29T09:03:55"
    expected_create_img_req = {
        "status": "VISIBLE",
        "amiID": "ami-123",
        "product": "RHEL",
        "description": "Released ami-rhel on 2020-10-29T09:03:55",
        "arch": "x86_64",
        "version": "none",
        "variant": "none",
        "region": "us-east-1",
    }

    client = AwsRHSMClient(
        "https://example.com", cert=("client.crt", "client.key"), max_retry_sleep=0.001
    )
    with patch("pubtools._marketplacesvm.services.rhsm.datetime") as now:
        now.now().replace().isoformat.return_value = date_now
        out = client.aws_create_image("ami-123", "ami-rhel", "x86_64", "RHEL", "us-east-1")
    assert out.result().ok
    assert m_create_image.call_count == 1
    assert m_create_image.last_request.json() == expected_create_img_req

    out = client.aws_create_image("ami-123", "ami-rhel", "x86_64", "RHEL", "us-east-1")
    assert not out.result().ok
    assert m_create_image.call_count == 2

    out = client.aws_create_image("ami-123", "ami-rhel", "x86_64", "RHEL", "us-east-1")
    assert isinstance(out.exception(), ConnectionError)
    assert caplog.messages == ["Failed to process request to RHSM with exception "]


def test_list_images(requests_mocker, caplog: LogCaptureFixture):
    """Test listing all images from rhsm while using pagination logic."""
    url = "https://example.com/v1/internal/cloud_access_providers/amazon/amis"
    caplog.set_level(logging.DEBUG)

    def create_response(amis_count, start):
        return {
            "status_code": 200,
            "json": {
                "pagination": {"count": amis_count},
                "body": [{"amiID": f"ami-{i}"} for i in range(start, start + amis_count)],
            },
        }

    responses = [
        create_response(750, 1),
        create_response(1, 751),
        create_response(0, 752),
    ]

    m_list_images = requests_mocker.register_uri("GET", url, responses)

    client = AwsRHSMClient(
        "https://example.com", cert=("client.crt", "client.key"), max_retry_sleep=0.001
    )

    image_ids = client.aws_list_image_ids()

    # there should be 3 calls, last won't get any data, so we stop requesting another page.
    # offset changes accordingly to items received
    assert m_list_images.call_count == 3
    for req_history, offset in zip(m_list_images.request_history, [0, 750, 751]):
        assert req_history.qs == {"limit": ["1000"], "offset": [str(offset)]}

    assert len(image_ids) == 751
    assert (
        "Listing all images from rhsm, https://example.com/v1/internal/cloud_access_providers/amazon/amis"  # noqa: E501
        in caplog.messages[0]
    )
