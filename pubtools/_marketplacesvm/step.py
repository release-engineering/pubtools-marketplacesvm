# SPDX-License-Identifier: GPL-3.0-or-later
import inspect
import logging
import threading
from concurrent.futures import Future
from typing import Any, Callable, Generator, List, Optional, Type, Union

from more_executors.futures import f_return, f_sequence

LOG = logging.getLogger("pubtools.marketplacesvm")


class StepDecorator(object):
    """Implementation of MarketplacesVMTask.step decorator. See that method for more info."""

    def __init__(self, name: str):
        """
        Instantiate the StepDecorator.

        Args:
            name (str)
                The name of the step.
        """
        self._name = name

    @property
    def human_name(self) -> str:
        """Return the step name."""
        return self._name

    @property
    def machine_name(self) -> str:
        """Return the machine readable step name."""
        return self._name.replace(" ", "-").lower()

    def __call__(self, fn: Callable[..., Any]):
        """
        Implement the step decorator when called.

        Args:
            fn (callable)
                The callable to be decorated.
            *args (list)
                The arguments to be passed to the callable.
            **kwargs (dict)
                The keyword arguments to be passed ot the callable.
        Returns:
            The step decorated callable.
        """

        def new_fn(instance, *args, **kwargs):
            if self.should_skip(instance):
                LOG.info(
                    "%s: skipped",
                    self.human_name,
                    extra={"event": {"type": "%s-skip" % self.machine_name}},
                )
                return args[0] if args else None

            logger = StepLogger(self)
            args = logger.log_start(args)

            try:
                ret = fn(instance, *args, **kwargs)
            except SystemExit as exc:
                if exc.code == 0:
                    logger.log_return()
                else:
                    logger.log_error()
                raise
            except Exception:
                logger.log_error()
                raise

            ret = logger.with_logs(ret)

            return ret

        return new_fn

    def should_skip(self, instance: Any) -> bool:
        """
        Check whether the instance is marked as skippable.

        Args:
            instance (object)
                The instance to check for the attribute "skip".
        Returns:
            True if the instance has the attribute "skip". False otherwise.
        """
        skip = (getattr(instance.args, "skip", None) or "").split(",")
        return self.machine_name in skip


# helpers used in implementation of decorator
def is_future(x: Type[object]) -> bool:
    """
    Ensure the given object is a Future.

    Args:
        x (object)
            The object to check if it's a Future.
    Returns:
        True if the object is a Future. False otherwise.
    """
    return hasattr(x, "add_done_callback")


def as_futures(args: Optional[List[Any]]) -> Optional[List[Future]]:
    """
    Return a list of future from the arguments.

    Args:
        args (list)
            The input arguments to process.
    Returns:
        list of futures when the first element from args is a Future.
    """
    arg0 = args[0] if args else None
    if is_future(arg0):
        return [arg0]

    if isinstance(arg0, list) and arg0 and is_future(arg0[0]):
        return arg0

    return None


class StepLogger(object):
    """
    Implement the logging when entering/exiting/failing a step.

    The main point of this class is to keep track of whether entering a step has been logged
    and make sure exiting a step can't be logged before entering.
    """

    def __init__(self, step: Any):
        """
        Instantiate the StepLogger.

        Args:
            step (object)
                The StepDecorator decorated class to initialize the logging.
        """
        self.step = step
        self.lock = threading.RLock()
        self.log_opened = False

    def log_start(self, args: Optional[List[Any]] = None) -> Optional[List[Any]]:
        """
        Start the logging for futures and generators.

        Args:
            args (list, optinal)
                List of arguments with future/generator to start the logging.
        Returns:
            The input args.
        """
        input_future = as_futures(args)

        if input_future:
            # This function takes future(s) as input: then the step is
            # only considered to start once *at least one* of the input futures
            # has completed
            for f in input_future:
                f.add_done_callback(lambda f: self.do_log_start() if not f.exception() else None)
            return args

        if args and inspect.isgenerator(args[0]):
            # This function takes a generator as input: then the step is
            # only considered to start once the first item is yielded
            # from that generator.
            new_args = [self.wrap_generator_start(args[0])]
            new_args.extend(args[1:])
            return new_args

        # Boring old function with no futures or generators, then it's
        # about to start immediately
        self.do_log_start()
        return args

    def do_log_start(self) -> None:
        """Log a step start."""
        with self.lock:
            if self.log_opened:
                return
            self.log_opened = True

            LOG.info(
                "%s: started",
                self.step.human_name,
                extra={"event": {"type": "%s-start" % self.step.machine_name}},
            )

    def log_error(self) -> None:
        """Log a step error."""
        self.log_start()

        LOG.error(
            "%s: failed",
            self.step.human_name,
            extra={"event": {"type": "%s-error" % self.step.machine_name}},
        )

    def log_return(self, return_value=None) -> None:
        """
        Log a completed step.

        Args:
            return_value (object)
                The step's return value.
        """
        return_future = as_futures([return_value]) or [f_return(None)]

        def do_log():
            self.log_start()

            LOG.info(
                "%s: finished",
                self.step.human_name,
                extra={"event": {"type": "%s-end" % self.step.machine_name}},
            )

        # The step is considered completed once *all* returned futures
        # have completed
        completed = f_sequence(return_future)
        completed.add_done_callback(
            lambda f: self.log_error() if completed.exception() else do_log()
        )

    def with_logs(self, ret: Union[Callable[..., Any], Generator[Any, Any, Any]]):
        """
        Return the logging end for a callable/generator.

        Args:
            ret: A callable or generator to set the log end.
        Returns:
            The logging end for the callable/generator.
        """
        if inspect.isgenerator(ret):
            return self.wrap_generator_end(ret)

        self.log_return(ret)
        return ret

    def wrap_generator_start(self, gen: Generator[Any, Any, Any]) -> Generator[Any, None, None]:
        """
        Wrap a generator with the logging start.

        Args:
            gen (generator)
                The generator to wrap with the logging start.
        Returns:
            The input generator.
        """
        try:
            first_item = next(gen)
        except StopIteration:
            # Generator stopped without yielding anything.
            self.do_log_start()
            return

        # Generator yielded first item, then we consider this step as 'started'.
        self.do_log_start()
        yield first_item

        # Now pass it through as usual from this point onwards.
        for item in gen:
            yield item

    def wrap_generator_end(self, gen: Generator[Any, Any, Any]) -> Generator[Any, None, None]:
        """
        Wrap a generator with the logging end.

        Args:
            gen (generator)
                The generator to wrap with the logging end.
        Returns:
            The input generator.
        """
        try:
            for item in gen:
                yield item
            self.log_return()
        except Exception:
            self.log_error()
            raise
