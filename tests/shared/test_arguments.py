# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
import sys
from argparse import ArgumentParser
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
import yaml
from _pytest.capture import CaptureFixture

from pubtools._marketplacesvm.arguments import (
    RepoFileQueryLoad,
    RepoQueryLoad,
    SplitAndExtend,
    from_environ,
)


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
def qrc1() -> List[Dict[str, Any]]:
    return [
        {
            "name": "test",
            "workflow": "stratosphere",
            "mappings": {
                "aws-na": {
                    "destinations": [
                        {
                            "architecture": "x86_64",
                            "destination": "185380b0-4e79-11ef-ae6c-3e3c9dfa9194",
                            "overwrite": False,
                            "restrict_version": True,
                        }
                    ]
                }
            },
        }
    ]


@pytest.fixture
def qrc2() -> List[Dict[str, Any]]:
    return [
        {
            "name": "test",
            "workflow": "community",
            "mappings": {
                "aws-us-storage": {
                    "destinations": [
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
                    ],
                    "provider": "AWS",
                }
            },
        }
    ]


@pytest.fixture
def qrc3(qrc1, qrc2) -> List[Dict[str, Any]]:
    return qrc1 + qrc2


@pytest.fixture
def qrc1_input(qrc1) -> str:
    return json.dumps(qrc1)


@pytest.fixture
def qrc2_input(qrc2) -> str:
    return json.dumps(qrc2)


@pytest.fixture
def qrc3_input(qrc3) -> str:
    return json.dumps(qrc3)


@pytest.mark.parametrize(
    "input, expected",
    [
        ('qrc1_input', 'qrc1'),
        ('qrc2_input', 'qrc2'),
        ('qrc3_input', 'qrc3'),
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


def test_repo_file_query_load(
    parser: ArgumentParser,
    tmpdir: pytest.Testdir,
) -> None:
    """Test RepoQueryLoad argparse Action."""
    p = tmpdir.mkdir('data').join('test.yaml')
    json_file = [{"testing": "test"}]
    p.write(yaml.dump(json_file))
    parser.add_argument("--repo-file", type=str, action=RepoFileQueryLoad)
    sys.argv = ["command", "--repo-file", f"{p}"]
    args = parser.parse_args()
    assert args.repo_file == [{"testing": "test"}]


def test_invalid_repo_query_load(parser: ArgumentParser, capsys: CaptureFixture) -> None:
    parser.add_argument("--foo", action=RepoQueryLoad)
    sys.argv = ["command", "--foo", "{\"foo\": \"bar\"}"]
    err = "argument --foo: Expected value to be a list, got: <class 'dict'>"
    with pytest.raises(SystemExit):
        parser.parse_args()

    assert err in capsys.readouterr().err


def test_invalid_repo_file_query_load(
    parser: ArgumentParser, capsys: CaptureFixture, tmpdir: pytest.Testdir
) -> None:
    p = tmpdir.mkdir('data').join('test.yaml')
    json_file = {"testing": "test"}
    p.write(yaml.dump(json_file))
    parser.add_argument("--foo", type=str, action=RepoFileQueryLoad)
    sys.argv = ["command", "--foo", f"{p}"]
    err = "argument --foo: Expected value to be a list, got: <class 'dict'>"
    with pytest.raises(SystemExit):
        parser.parse_args()

    assert err in capsys.readouterr().err
