# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import sys
from logging import Logger
from typing import Generator, Union

import pytest
from pytest import MonkeyPatch

from pubtools._marketplacesvm.task import MarketplacesVMTask


class MyTask(MarketplacesVMTask):
    def run(self) -> None:
        # nothing to do
        pass


def simple_basic_config(level: Union[int, str], **_kwargs) -> None:
    """
    Define a similar config as logging.basicConfig with some differences.

    - it only sets the level, ignores other arguments
    - it works every time (instead of only once per process)
    """
    logging.getLogger().setLevel(level)


@pytest.fixture(autouse=True)
def clean_root_logger(monkeypatch: MonkeyPatch) -> Generator[None, None, None]:
    """Hijack logging.basicConfig and reset root logger level around tests."""
    monkeypatch.setattr(logging, "basicConfig", simple_basic_config)

    root = logging.getLogger()
    level = root.level
    yield
    root.setLevel(level)


# All loggers below are forced to NOTSET before being yielded, because
# other tests might have already adjusted their level


@pytest.fixture
def tier1_logger() -> Generator[Logger, None, None]:
    """Test the logger for this project."""
    out = logging.getLogger("pubtools.marketplacesvm")
    level = out.level
    out.setLevel(logging.NOTSET)
    yield out
    out.setLevel(level)


@pytest.fixture
def tier2_logger() -> Generator[Logger, None, None]:
    """Test the logger from the same family of projects."""
    out = logging.getLogger("pubtools.some-pubtools-project")
    level = out.level
    out.setLevel(logging.NOTSET)
    yield out
    out.setLevel(level)


@pytest.fixture
def tier3_logger() -> Generator[Logger, None, None]:
    """Test a completely foreign logger from an unrelated project."""
    out = logging.getLogger("some-foreign-logger")
    level = out.level
    out.setLevel(logging.NOTSET)
    yield out
    out.setLevel(level)


def test_default_logs(tier1_logger: Logger, tier2_logger: Logger, tier3_logger: Logger) -> None:
    """Test all loggers use INFO by default."""
    task = MyTask()
    sys.argv = ["my-task"]
    task.main()

    assert tier1_logger.getEffectiveLevel() == logging.INFO
    assert tier2_logger.getEffectiveLevel() == logging.INFO
    assert tier3_logger.getEffectiveLevel() == logging.INFO


def test_debug1_logs(tier1_logger: Logger, tier2_logger: Logger, tier3_logger: Logger) -> None:
    """Ensure tier 1 loggers use DEBUG if --debug is provided."""
    task = MyTask()
    sys.argv = ["my-task", "--debug"]
    task.main()

    assert tier1_logger.getEffectiveLevel() == logging.DEBUG
    assert tier2_logger.getEffectiveLevel() == logging.INFO
    assert tier3_logger.getEffectiveLevel() == logging.INFO


def test_debug2_logs(tier1_logger: Logger, tier2_logger: Logger, tier3_logger: Logger) -> None:
    """Ensure Tier 1 & 2 loggers use DEBUG if --debug is provided twice."""
    task = MyTask()
    sys.argv = ["my-task", "-dd"]
    task.main()

    assert tier1_logger.getEffectiveLevel() == logging.DEBUG
    assert tier2_logger.getEffectiveLevel() == logging.DEBUG
    assert tier3_logger.getEffectiveLevel() == logging.INFO


def test_debug3_logs(tier1_logger: Logger, tier2_logger: Logger, tier3_logger: Logger) -> None:
    """Ensure all loggers use DEBUG if --debug is provided thrice."""
    task = MyTask()
    sys.argv = ["my-task", "--debug", "-d", "--debug"]
    task.main()

    assert tier1_logger.getEffectiveLevel() == logging.DEBUG
    assert tier2_logger.getEffectiveLevel() == logging.DEBUG
    assert tier3_logger.getEffectiveLevel() == logging.DEBUG
