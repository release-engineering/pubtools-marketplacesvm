# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

from pubtools._marketplacesvm.tasks.push import MarketplacesVMPush, entry_point

from ..command import CommandTester


def test_do_push(command_tester: CommandTester) -> None:
    """Test a successfull push."""
    command_tester.test(
        lambda: entry_point(MarketplacesVMPush),
        [
            "test-push",
            "--starmap-url",
            "https://starmap-example.com",
            "--credentials",
            "eyJtYXJrZXRwbGFjZV9hY2NvdW50IjogInRlc3QtbmEiLCAiYXV0aCI6eyJmb28iOiJiYXIifQo=",
            "--debug",
            "koji:https://fakekoji.com?vm_build=build",
        ],
    )

    # FIXME: Remove the lines below once the push phases are implemented
    with pytest.raises(NotImplementedError):
        MarketplacesVMPush().run()
