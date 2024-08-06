# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import sys
import textwrap
import traceback
from argparse import ArgumentParser, Namespace, RawDescriptionHelpFormatter
from collections import namedtuple
from typing import Optional

from pubtools.pluggy import task_context

from .step import StepDecorator
from .utils import BuildIdBorg

LOG = logging.getLogger("pubtools.marketplacesvm")
LOG_FORMAT = "%(asctime)s [%(levelname)-8s] %(message)s"


RUN_RESULT = namedtuple('RUN_RESULT', ['success', 'skipped', 'collected_result'])


class MarketplacesVMTask(object):
    """
    Base class for MarketplacesVM CLI tasks.

    Instances for MarketplacesVMTask subclass may be obtained to request
    tasks like push, scan, etc.

    This class provides a CLI parser for the Marketplaces VM tasks. Parser is
    configured with minimal options which can be extended by subclass.
    """

    def __init__(self) -> None:
        """Instantiate the MarketplacesVMTask."""
        super(MarketplacesVMTask, self).__init__()

        self._args: Optional[Namespace] = None

        self.parser = ArgumentParser(
            description=self.description, formatter_class=RawDescriptionHelpFormatter
        )
        self.builds_borg = BuildIdBorg()
        self._basic_args()
        self.add_args()

    @property
    def description(self) -> str:
        """
        Define the description for argument parser; shows up in generated docs.

        Defaults to the class doc string with some whitespace fixes.
        """
        # Doc strings are typically written having the first line starting
        # without whitespace, and all other lines starting with whitespace.
        # That would be formatted oddly when copied into RST verbatim,
        # so we'll dedent all lines *except* the first.
        split = (self.__doc__ or "<undocumented task>").splitlines(True)
        firstline = split[0]
        rest = "".join(split[1:])
        rest = textwrap.dedent(rest)
        out = "".join([firstline, rest]).strip()

        # To keep separate paragraphs, we use RawDescriptionHelpFormatter,
        # but that means we have to wrap it ourselves, so do that here.
        paragraphs = out.split("\n\n")
        chunks = ["\n".join(textwrap.wrap(p)) for p in paragraphs]
        return "\n\n".join(chunks)

    @property
    def args(self) -> Namespace:
        """
        Store the parsed args from the cli.

        returns the args if available from previous parse
        else parses with defined options and return the args.
        """
        if not self._args:
            self._args = self.parser.parse_args()
        return self._args

    @classmethod
    def step(cls, name) -> StepDecorator:
        """
        Implement a decorator to mark an instance method as a discrete workflow step.

        Marking a method as a step has effects:

        - Log messages will be produced when entering and leaving the method
        - The method can be skipped if requested by the caller (via --skip argument)

        Steps may be written as plain blocking functions, as non-blocking
        functions which accept or return Futures, or as generators.
        When futures are accepted or returned, a single Future or a list of
        Futures may be used.

        When Futures are used, the following semantics apply:

        - The step is considered *started* once *any* of the input futures has finished
        - The step is considered *failed* once *any* of the output futures has failed
        - The step is considered *finished* once *all* of the output futures have finished

        When generators are used, the following semantics apply:

        - The step is considered *started* once the input generator has yielded at least
          one item, or has completed; or, immediately if the input is not a generator.
        - The step is considered *failed* if it raised an exception.
        - The step is considered *finished* once all items have been yielded.
        """
        return StepDecorator(name)

    def _basic_args(self) -> None:
        # minimum args required for a Marketplaces VM CLI task
        self.parser.add_argument(
            "--debug",
            "-d",
            action="count",
            default=0,
            help=("Show debug logs; can be provided up to three times to enable more logs"),
        )

    def _setup_logging(self):
        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)  # NOSONAR

        # All loggers will now log at INFO or higher.
        # If we were given --debug, enable DEBUG level from some loggers,
        # depending on how many were given.
        debug_loggers = []
        if self.args.debug >= 1:
            # debug level 1: enable DEBUG from this project
            debug_loggers.append("pubtools.marketplacesvm")
        if self.args.debug >= 2:
            # debug level 2: enable DEBUG from closely related projects.
            debug_loggers.extend(["pubtools", "pushsource", "cloudimg", "cloudpub"])
        if self.args.debug >= 3:
            # debug level 3: enable DEBUG from root logger
            # (potentially very, very verbose!)
            debug_loggers.append(None)

        # Disable noisy logs from SDK
        if self.args.debug < 4:
            # Disable noisy Azure HTTPS requests debug/info logs
            azure_logger = "azure.core.pipeline.policies.http_logging_policy"
            logging.getLogger(azure_logger).setLevel(logging.WARNING)

        for logger_name in debug_loggers:
            logging.getLogger(logger_name).setLevel(logging.DEBUG)

    def add_args(self):
        """
        Add parser options/arguments for a task.

        e.g. self.parser.add_argument("option", help="help text")
        """
        # Calling super add_args if it exists allows this class and
        # Service classes to be inherited in either order without breaking.
        from_super = getattr(super(MarketplacesVMTask, self), "add_args", lambda: None)
        from_super()

    def run(self, collect_results: bool = True, allow_empty_targets: bool = False) -> RUN_RESULT:
        """Implement a specific task."""
        raise NotImplementedError()

    def main(self, **kwargs):
        """Define the main method to be called by the entrypoint of the task."""
        with task_context():
            # setup the logging as required
            self._setup_logging()

            try:
                res = self.run(**kwargs)
                if not res.success:
                    sys.exit(30)
            except:  # noqa: E722
                traceback.print_exc()
                raise
        return 0
