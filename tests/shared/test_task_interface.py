# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests ensuring all task modules have a consistent interface."""
import argparse
import sys
from typing import Any, Dict

import pytest


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
