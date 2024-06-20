# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests ensuring all task modules have a consistent interface."""
import argparse
import contextlib
import io
import sys
from typing import Any, Dict
from unittest import mock

import pytest

from pubtools._marketplacesvm.task import MarketplacesVMTask


@pytest.fixture(
    params=[
        "pubtools._marketplacesvm.tasks.push",
        "pubtools._marketplacesvm.tasks.community_push",
        "pubtools._marketplacesvm.tasks.combined_push",
    ]
)
def task_module(request: pytest.FixtureRequest):
    __import__(request.param)
    return sys.modules[request.param]


def test_doc_parser(task_module: Dict[str, Any]) -> None:
    """
    Test the doc_parser.

    Every task module should have a doc_parser which can be called without arguments and returns an
    ArgumentParser. This supports the generation of docs from argument parsers.
    """
    fn = getattr(task_module, "doc_parser")
    parser = fn()
    assert isinstance(parser, argparse.ArgumentParser)


def test_entry_point(task_module: Dict[str, Any]) -> None:
    """Every task module should have a callable entry_point."""
    fn = getattr(task_module, "entry_point")
    assert callable(fn)

    # Default action for all entry points without parameters is to exit
    with pytest.raises(SystemExit):
        fn()


def test_exception_traceback(task_module: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the traceback is properly caught in case of an unexpected exception."""
    # Since we're not using a CommandTester we must ensure that only `run` is called within `main`
    # as it will raise `NotImplementedError` which will be caught by the `try/except` in `main`.
    monkeypatch.setattr(MarketplacesVMTask, "_setup_logging", mock.MagicMock())

    output = io.StringIO()
    fn = getattr(task_module, "entry_point")

    with contextlib.redirect_stderr(output):
        with pytest.raises(NotImplementedError):
            fn(cls=MarketplacesVMTask)

    assert "Traceback (most recent call last)" in output.getvalue()
    assert "NotImplementedError" in output.getvalue()
