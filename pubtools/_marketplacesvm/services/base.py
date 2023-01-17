# SPDX-License-Identifier: GPL-3.0-or-later
from argparse import ArgumentParser, Namespace


class Service:
    """
    Define a mix-in class to be inherited for access to specific services.

    The Service class is used as follows:

    - for a particular service needed by certain tasks (e.g. a Pulp client,
      a FastPurge client), implement a subclass of Service
    - in the subclass, if there are associated command-line arguments, override
      add_service_args to configure those
    - in the subclass, add the properties which should be exposed by that service
      (often just one)

    Once done, every task which needs that service can inherit from the needed
    service implementation(s) to access it with consistent argument handling.
    """

    def add_args(self) -> None:
        """
        Override the ``add_args`` method from MarketplacesVMTask.

        These classes can be mixed in both before and after MarketplacesVMTask,
        hence the dynamic add_args and parser lookups.
        """
        super_add_args = getattr(super(Service, self), "add_args", lambda: None)
        super_add_args()

        parser = getattr(self, "parser", ArgumentParser())
        self.add_service_args(parser)

    def add_service_args(self, parser: ArgumentParser) -> None:
        """
        Implement me in subclasses to add arguments particular to a service (if any).

        Make sure to call super() when overriding.
        """

    @property
    def _service_args(self) -> Namespace:
        """
        Return the arguments from the current Service subclass.

        Expected to be mixed in with a class providing "args" property.
        """
        if not hasattr(self, "args"):
            raise RuntimeError("BUG: Service inheritor must provide 'args'")
        return self.args
