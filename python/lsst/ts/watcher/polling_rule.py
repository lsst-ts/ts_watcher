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

import asyncio

from lsst.ts import utils

from .base_rule import BaseRule


class PollingRule(BaseRule):
    """Base class for watcher rules that poll for data.

    Regularly call `update_alarm_severity` with no arguments,
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
    log : `logging.Logger`, optional
        Parent logger.

    Attributes
    ----------
    BaseRule attributes
        All attributes from `BaseRule`, plus:
    poll_start_tai : `float`
        The time (TAI, unix seconds) at which polling began.
    poll_loop_task : `asyncio.Future`
        Task that runs the polling loop.
    """

    def __init__(self, config, name, remote_info_list, log=None):
        self.poll_start_tai = utils.current_tai()
        self.poll_loop_task = utils.make_done_future()
        super().__init__(
            config=config, name=name, remote_info_list=remote_info_list, log=log
        )

    def start(self):
        self.poll_loop_task.cancel()
        self.poll_loop_task = asyncio.create_task(self.poll_loop())

    def stop(self):
        self.poll_loop_task.cancel()

    async def poll_loop(self):
        # Keep track of when polling begins
        # in order to avoid confusing "no data ever seen"
        # with "all data is older than max_data_age"
        self.poll_start_tai = utils.current_tai()
        while True:
            await self.update_alarm_severity()
            await asyncio.sleep(self.config.poll_interval)
