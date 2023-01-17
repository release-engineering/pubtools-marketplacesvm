# SPDX-License-Identifier: GPL-3.0-or-later
import os
import sys

import pytest
import requests_mock
from pushcollector import Collector
from pushsource import Source

from .collector import FakeCollector
from .command import CommandTester


@pytest.fixture(autouse=True)
def save_argv():
    """
    Save and restore sys.argv around each test.

    This is an autouse fixture, so tests can freely modify
    sys.argv without concern.
    """
    orig_argv = sys.argv[:]
    yield
    sys.argv[:] = orig_argv


@pytest.fixture(autouse=True)
def pushsource_reset():
    """
    Reset pushsource library after each test.

    Allows tests to adjust pushsource backends without interfering
    with each other.
    """
    yield
    Source.reset()


@pytest.fixture(autouse=True)
def home_tmpdir(tmpdir, monkeypatch):
    """
    Point HOME environment variable underneath tmpdir for the duration of tests.

    This is an autouse fixture because certain used libraries
    and our own pulp fake are influenced by files under $HOME,
    and for tests which actually need it, we should explicitly
    set up anything needed there instead of inheriting the
    user's environment.
    """
    homedir = str(tmpdir.mkdir("home"))
    monkeypatch.setenv("HOME", homedir)


@pytest.fixture(autouse=True)
def requests_mocker():
    """Mock all requests.

    This is an autouse fixture so that tests can't accidentally
    perform real requests without being noticed.
    """
    with requests_mock.Mocker() as m:
        yield m


@pytest.fixture(autouse=True)
def fake_collector():
    """
    Install fake in-memory backend for pushcollector library.

    Recorded push items can be tested via this instance.

    This is an autouse fixture so that all tests will automatically
    use the fake backend.
    """
    collector = FakeCollector()

    Collector.register_backend("pubtools-pulp-test", lambda: collector)
    Collector.set_default_backend("pubtools-pulp-test")

    yield collector

    Collector.set_default_backend(None)


@pytest.fixture
def data_path():
    """Return the path to the tests/data dir used to store extra files for testing."""
    return os.path.join(os.path.dirname(__file__), "data")


@pytest.fixture
def command_tester(request, tmpdir, caplog):
    """Yield a configured instance of CommandTester to test command's output against expected."""
    yield CommandTester(request.node, tmpdir, caplog)
