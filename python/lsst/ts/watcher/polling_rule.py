from __future__ import annotations

# This file is part of ts_watcher.
#
# Developed for Vera C. Rubin Observatory Telescope and Site Systems.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

__all__ = ["PollingRule"]

import abc
import asyncio
import types
import typing

from lsst.ts import utils

from .base_rule import BaseRule

if typing.TYPE_CHECKING:
    from .alarm import Alarm
    from .remote_info import RemoteInfo


class PollingRule(BaseRule):
    """Base class for watcher rules that poll for data.

    Regularly call the rule with no arguments,
    at the interval specified by config.poll_interval.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
        Must include a float field named "poll_interval"
        set to the polling interval in seconds.
    name : `str`
        Name of alarm. This must be unique among all alarms
        and should be of the form system.[subsystem....]_name
        so that groups of related alarms can be acknowledged.
    remote_info_list : `list` [`RemoteInfo`]
        Information about the remotes used by this rule.
    alarm_list : `list` [`Alarm`]

    Attributes
    ----------
    poll_start_tai : `float`
        The time at which polling began after most recently starting the rule.
        TAI (unix seconds). 0 when first constructed.
    alarm : `Alarm`
        The alarm associated with this rule.
    remote_keys : `frozenset` [`tuple` [`str`, `int`]]
        Set of remote keys. Each element is a tuple of:

        * SAL component name (e.g. "ATPtg")
        * SAL index
    """

    def __init__(
        self,
        config: types.SimpleNamespace,
        name: str,
        remote_info_list: list[RemoteInfo],
        alarm_list: list[Alarm] | None = None,
    ):
        self.poll_start_tai = 0
        self.poll_loop_task = utils.make_done_future()
        super().__init__(
            config=config,
            name=name,
            remote_info_list=remote_info_list,
            alarm_list=alarm_list,
        )

    def start(self) -> None:
        self.poll_loop_task.cancel()
        self.poll_loop_task = asyncio.create_task(self.poll_loop())

    def stop(self) -> None:
        self.poll_loop_task.cancel()

    async def poll_loop(self) -> None:
        self.poll_start_tai = utils.current_tai()
        while True:
            await self.poll_once()
            await asyncio.sleep(self.config.poll_interval)

    @abc.abstractmethod
    async def poll_once(self, is_first: bool) -> None:
        """Poll the alarm once.

        Parameters
        ----------
        is_first : `bool`
            True if this is the first time poll_once has been called
            since the rule was started.

        Returns
        -------
        severity, reason
        """
        raise NotImplementedError()
