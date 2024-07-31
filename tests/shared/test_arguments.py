# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
import sys
from argparse import ArgumentParser
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from starmap_client.models import QueryResponse

from pubtools._marketplacesvm.arguments import RepoQueryLoad, SplitAndExtend, from_environ


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


@pytest.fixture
def qr1() -> Dict[str, Any]:
    return {
        "name": "test",
        "workflow": "stratosphere",
        "mappings": {
            "aws-na": [
                {
                    "architecture": "x86_64",
                    "destination": "185380b0-4e79-11ef-ae6c-3e3c9dfa9194",
                    "overwrite": False,
                    "restrict_version": True,
                }
            ]
        },
    }


@pytest.fixture
def qr2() -> Dict[str, Any]:
    return {
        "name": "test",
        "workflow": "community",
        "mappings": {
            "aws-us-storage": [
                {
                    "architecture": "x86_64",
                    "destination": "test1",
                    "overwrite": False,
                    "restrict_version": False,
                },
                {
                    "architecture": "x86_64",
                    "destination": "test2",
                    "overwrite": False,
                    "restrict_version": False,
                },
                {
                    "architecture": "x86_64",
                    "destination": "test3",
                    "overwrite": False,
                    "restrict_version": False,
                },
            ]
        },
    }


@pytest.fixture
def qr1_input(qr1) -> str:
    return json.dumps(qr1)


@pytest.fixture
def qr1_output(qr1) -> List[QueryResponse]:
    return [QueryResponse.from_json(qr1)]


@pytest.fixture
def qr2_input(qr2) -> str:
    return json.dumps(qr2)


@pytest.fixture
def qr2_output(qr2) -> List[QueryResponse]:
    return [QueryResponse.from_json(qr2)]


@pytest.fixture
def qr3_input(qr1, qr2) -> str:
    return json.dumps([qr1, qr2])


@pytest.fixture
def qr3_output(qr1_output, qr2_output) -> List[QueryResponse]:
    return qr1_output + qr2_output


@pytest.mark.parametrize(
    "input, expected",
    [
        ('qr1_input', 'qr1_output'),
        ('qr2_input', 'qr2_output'),
        ('qr3_input', 'qr3_output'),
    ],
)
def test_repo_query_load(
    parser: ArgumentParser,
    input: str,
    expected: str,
    request: pytest.FixtureRequest,
) -> None:
    """Test RepoQueryLoad argparse Action."""
    parser.add_argument("--repo", type=str, action=RepoQueryLoad)
    sys.argv = ["command", "--repo", request.getfixturevalue(input)]
    args = parser.parse_args()
    assert args.repo == request.getfixturevalue(expected)
