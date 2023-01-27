# SPDX-License-Identifier: GPL-3.0-or-later
import sys
from unittest.mock import patch

import pytest
from _pytest.capture import CaptureFixture

from pubtools._marketplacesvm.task import MarketplacesVMTask

step = MarketplacesVMTask.step


class TestMarketplacesVMTask(MarketplacesVMTask):
    def add_args(self) -> None:
        super(TestMarketplacesVMTask, self).add_args()
        self.parser.add_argument("--skip", help="skip a step")

    @step("task1")
    def task1(self) -> None:
        print("task1")

    @step("task2")
    def task2(self) -> None:
        print("task2")

    def run(self) -> None:
        self.task1()
        self.task2()


def test_skip(capsys: CaptureFixture) -> None:
    """Test that a method using step decorator is skipped when its name is provided with --skip."""
    task = TestMarketplacesVMTask()
    arg = ["", "--skip", "task1"]
    with patch.object(sys, "argv", arg):
        task.main()

    out, _ = capsys.readouterr()
    assert "task2" in out
    assert "task1" not in out


def test_task_run() -> None:
    """Exit with error if run() is not implemented."""
    with MarketplacesVMTask() as task:
        with pytest.raises(NotImplementedError):
            task.run()


def test_main() -> None:
    """Test the main entrypoint with contextmanager."""
    with MarketplacesVMTask() as task:
        arg = ["", "-d", "-d", "-d", "-d"]
        with patch.object(sys, "argv", arg):
            with patch("pubtools._marketplacesvm.task.MarketplacesVMTask.run"):
                assert task.main() == 0


def test_description():
    """The description is initialized from subclass docstring, de-dented."""

    class MyTask(MarketplacesVMTask):
        """This is an example task subclass.

        It has a realistic multi-line doc string:

            ...and may have several levels of indent.
        """

    assert MyTask().description == (
        "This is an example task subclass.\n\n"
        "It has a realistic multi-line doc string:\n\n"
        "    ...and may have several levels of indent."
    )
