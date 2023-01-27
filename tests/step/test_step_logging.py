# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import sys
from concurrent.futures import Future
from typing import Generator, List, NoReturn

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal

import pytest
from _pytest.logging import LogCaptureFixture

from pubtools._marketplacesvm.task import MarketplacesVMTask

step = MarketplacesVMTask.step


class SimulatedError(RuntimeError):
    pass


class FakeTask:
    @property
    def args(self) -> object:
        # Not a real task, no args from user
        return object()

    @step("fail if neq")
    def fail_if_neq(self, x: int, y: int) -> None:
        if x != y:
            raise SimulatedError()

    @step("gen out")
    def gen_out(self, n: int) -> Generator[int, None, None]:
        while n > 0:
            yield n
            n = n - 1

    @step("gen in-out")
    def gen_in_out(self, inputs):
        for item in inputs:
            yield item
        yield "last"

    @step("gen weird")
    def gen_weird(
        self, value: bool = False, error: bool = False
    ) -> Generator[Literal[True], None, None]:
        if error:
            raise RuntimeError("whoops")
        if value:
            yield value

    @step("future in-out")
    def future_in_out(self, f: List[Future], fail: bool = False) -> Future:
        if fail:
            raise SimulatedError()
        return Future()

    @step("exit with code")
    def exit_with_code(self, code: int) -> NoReturn:
        sys.exit(code)

    @step("future in-out list")
    def future_in_out_list(self, f: Future) -> List[Future]:
        return [Future(), Future()]


def test_success(caplog: LogCaptureFixture) -> None:
    """Plain blocking step should log when entered/exited."""
    caplog.set_level(logging.INFO)
    task = FakeTask()
    task.fail_if_neq(1, 1)

    assert caplog.messages == ["fail if neq: started", "fail if neq: finished"]


def test_fail(caplog: LogCaptureFixture) -> None:
    """Plain blocking step should log when entered/failed."""
    caplog.set_level(logging.INFO)
    task = FakeTask()

    with pytest.raises(SimulatedError):
        task.fail_if_neq(1, 2)

    assert caplog.messages == ["fail if neq: started", "fail if neq: failed"]


def test_future_logging(caplog: LogCaptureFixture) -> None:
    """Step taking/returning future should log when futures progress."""
    caplog.set_level(logging.INFO)

    task = FakeTask()

    in_fs: List = [Future(), Future()]
    out_f = task.future_in_out(in_fs)

    # The step shouldn't be counted as entered yet.
    assert caplog.messages == []

    # If *any* input future is resolved, then the step counts as started,
    # but not yet finished.
    in_fs[0].set_result(None)
    assert caplog.messages == ["future in-out: started"]

    # There should not be duplicate logs when other input futures resolve.
    in_fs[1].set_result(None)
    assert caplog.messages == ["future in-out: started"]

    # If the output future is resolved, then the step counts as finished.
    out_f.set_result(None)
    assert caplog.messages == ["future in-out: started", "future in-out: finished"]


def test_future_output_failed(caplog: LogCaptureFixture) -> None:
    """Step returning future should log when output fails."""
    caplog.set_level(logging.INFO)

    task = FakeTask()

    in_f: Future = Future()
    in_f.set_result("abc")

    out_f = task.future_in_out(in_f)

    # It's now in progress.
    assert caplog.messages == ["future in-out: started"]

    # If the output future is failed, then step is considered failed
    out_f.set_exception(SimulatedError())
    assert caplog.messages == ["future in-out: started", "future in-out: failed"]


def test_future_list_failed(caplog: LogCaptureFixture) -> None:
    """Step returning list of futures should log when any fails."""
    caplog.set_level(logging.INFO)

    task = FakeTask()

    in_f: Future = Future()
    out_fs = task.future_in_out_list(in_f)

    # No logs yet.
    assert caplog.messages == []

    # If the output future is failed, then step is immediately considered failed
    out_fs[0].set_exception(SimulatedError())
    assert caplog.messages == [
        "future in-out list: started",
        "future in-out list: failed",
    ]

    # Nothing changes if another future completes.
    out_fs[1].set_result(None)
    assert caplog.messages == [
        "future in-out list: started",
        "future in-out list: failed",
    ]


def test_future_fails_not_started(caplog: LogCaptureFixture) -> None:
    """Step which immediately fails given incomplete futures should have coherent logs."""
    caplog.set_level(logging.INFO)

    task = FakeTask()

    in_f: Future = Future()
    with pytest.raises(SimulatedError):
        task.future_in_out(in_f, fail=True)

    # Although it takes a future which is not resolved yet,
    # it's immediately marked as both started & failed due
    # to the exception being raised
    assert caplog.messages == ["future in-out: started", "future in-out: failed"]

    # Input future being resolved doesn't change the logs at all.
    in_f.set_result(None)
    assert caplog.messages == ["future in-out: started", "future in-out: failed"]


def test_exit_success(caplog: LogCaptureFixture) -> None:
    """Step exiting successfully is considered finished."""
    caplog.set_level(logging.INFO)

    task = FakeTask()

    with pytest.raises(SystemExit):
        task.exit_with_code(0)

    assert caplog.messages == ["exit with code: started", "exit with code: finished"]


def test_exit_fail(caplog: LogCaptureFixture) -> None:
    """Step exiting unsuccessfully is considered failed."""
    caplog.set_level(logging.INFO)

    task = FakeTask()

    with pytest.raises(SystemExit):
        task.exit_with_code(123)

    assert caplog.messages == ["exit with code: started", "exit with code: failed"]


def test_generator_logging(caplog: LogCaptureFixture) -> None:
    """A typical generator logs start/stop messages appropriately."""
    caplog.set_level(logging.INFO)

    task = FakeTask()

    # This generator is expected to produce exactly 4 items.
    items_step1 = task.gen_out(4)

    # The step above counts as immediately started when called, since it doesn't
    # take any async type as input.
    assert caplog.messages == ["gen out: started"]

    items_step2 = task.gen_in_out(items_step1)

    # gen_in_out is not immediately considered started, since the first step will
    # not have yielded anything yet.
    assert caplog.messages == ["gen out: started"]

    # but if we iterate once...
    next(items_step2)

    # Now both steps are in progress.
    assert caplog.messages == ["gen out: started", "gen in-out: started"]

    # If we iterate enough so that the first generator is exhausted...
    next(items_step2)
    next(items_step2)
    next(items_step2)
    next(items_step2)

    # Then we should see that the first step is finished, while the second is still in progress
    assert caplog.messages == [
        "gen out: started",
        "gen in-out: started",
        "gen out: finished",
    ]

    # next one more time should tell us there's nothing more...
    try:
        next(items_step2)
    except StopIteration:
        pass

    # and that should mark the second step as finished too
    assert caplog.messages == [
        "gen out: started",
        "gen in-out: started",
        "gen out: finished",
        "gen in-out: finished",
    ]


def test_generator_noop(caplog: LogCaptureFixture) -> None:
    """A generator which returns without yielding anything logs appropriately."""
    caplog.set_level(logging.INFO)

    task = FakeTask()

    # This generator will not produce anything.
    items_step1 = task.gen_weird()
    items_step2 = task.gen_in_out(items_step1)

    # step 1 above counts as immediately started when called, since it doesn't
    # take any async type as input.
    assert caplog.messages == ["gen weird: started"]

    # iterating once on the second step should mark the first step as done
    # and second as started
    next(items_step2)
    assert caplog.messages == [
        "gen weird: started",
        "gen weird: finished",
        "gen in-out: started",
    ]


def test_generator_failed(caplog: LogCaptureFixture) -> None:
    """A generator which raises an exception logs appropriately."""
    caplog.set_level(logging.INFO)

    task = FakeTask()

    # This generator will raise an exception.
    items = task.gen_weird(error=True)

    # The step above counts as immediately started when called, since it doesn't
    # take any async type as input.
    assert caplog.messages == ["gen weird: started"]

    # it should not be possible to do even a single iteration - it should crash
    try:
        next(items)
    except RuntimeError:
        pass

    # And that should mark the step as failed
    assert caplog.messages == ["gen weird: started", "gen weird: failed"]
