# SPDX-License-Identifier: GPL-3.0-or-later
import os
import sys
from argparse import ArgumentParser
from typing import List
from unittest.mock import patch

import pytest

from pubtools._marketplacesvm.arguments import SplitAndExtend, from_environ


@pytest.fixture
def parser():
    return ArgumentParser()


@pytest.mark.parametrize(
    "argv, expected",
    [
        (["--option", "a"], ["a"]),
        (["--option", "a,"], ["a", ""]),
        (["--option", "a,b"], ["a", "b"]),
        (["--option", "a,b,"], ["a", "b", ""]),
        (["--option", ",a,b"], ["", "a", "b"]),
        (["--option", "a,,b"], ["a", "", "b"]),
        (["--option", "a", "--option", "b"], ["a", "b"]),
        (["--option", "a,b", "--option", "c"], ["a", "b", "c"]),
        (["--option", "a", "--option", "b,c"], ["a", "b", "c"]),
        (["--option", "a,,b", "--option", ",c,"], ["a", "", "b", "", "c", ""]),
    ],
)
def test_split_and_extend(parser: ArgumentParser, argv: List[str], expected: List[str]) -> None:
    """Test SplitAndExtend argparse Action."""
    parser.add_argument("--option", type=str, action=SplitAndExtend)
    sys.argv = ["command"] + argv
    args = parser.parse_args()
    assert args.option == expected


@pytest.mark.parametrize("delimiter", [",", ".", "-", "/"])
def test_split_and_extend_varying_delimiters(parser: ArgumentParser, delimiter: str) -> None:
    """Test using different delimiters using a single option instance."""
    expected = ["a", "b", "x", "y"]
    parser.add_argument("--option", type=str, action=SplitAndExtend, split_on=delimiter)
    sys.argv = ["command", "--option", delimiter.join(expected)]
    args = parser.parse_args()
    assert args.option == expected


@patch.dict(os.environ, {"MY_SUPER_SECRET": "PASSWORD"})
def test_from_environ(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--secret",
        type=from_environ("MY_SUPER_SECRET"),
        default="",
    )
    sys.argv = ["command"]
    args = parser.parse_args()
    assert args.secret == "PASSWORD"
