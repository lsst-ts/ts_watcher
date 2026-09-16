# This file is part of ts_watcher.
#
# Developed for the Vera C. Rubin Observatory Telescope and Site Systems.
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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

import asyncio
import types
import unittest

import pytest
import yaml

from lsst.ts.salobj import Controller, delete_kafka_topics, set_test_topic_subname
from lsst.ts.watcher import Model
from lsst.ts.watcher.rules import ClosedLoopDisabled
from lsst.ts.xml.enums.MTAOS import ClosedLoopState
from lsst.ts.xml.enums.Scheduler import DetailedState
from lsst.ts.xml.enums.Watcher import AlarmSeverity

STD_TIMEOUT = 5


class TestClosedLoopDisabled(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        set_test_topic_subname(randomize=True)
        return super().setUp()

    async def asyncTearDown(self) -> None:
        await delete_kafka_topics()
        return await super().asyncTearDown()

    async def test_basics(self):
        schema = ClosedLoopDisabled.get_schema()
        assert schema is not None

        config = ClosedLoopDisabled.make_config()

        assert config.alarm_severity == AlarmSeverity.WARNING.name

        config = ClosedLoopDisabled.make_config(alarm_severity=AlarmSeverity.CRITICAL.name)

        assert config.alarm_severity == AlarmSeverity.CRITICAL.name

    async def test_call(self):

        watcher_config_dict = yaml.safe_load(
            """
            disabled_sal_components: []
            auto_acknowledge_delay: 3600
            auto_unacknowledge_delay: 3600
            rules:
            - classname: ClosedLoopDisabled
              configs:
                - alarm_severity: WARNING
            escalation: []
            """
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)

        async with (
            Controller("Scheduler", 1) as scheduler,
            Controller("MTAOS") as mtaos,
            Model(scheduler.domain, config=watcher_config) as model,
        ):
            await model.enable()

            assert len(model.rules) == 1

            rule_name = "ClosedLoopDisabled"
            rule = model.rules[rule_name]
            rule.alarm.init_severity_queue()

            await scheduler.evt_detailedState.set_write(substate=DetailedState.IDLE)

            severity = await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)
            assert severity == AlarmSeverity.NONE

            await mtaos.evt_closedLoopState.set_write(state=ClosedLoopState.IDLE)
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)

            await scheduler.evt_detailedState.set_write(substate=DetailedState.RUNNING)
            severity = await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)
            assert severity == AlarmSeverity.WARNING

            await mtaos.evt_closedLoopState.set_write(state=ClosedLoopState.WAITING_IMAGE)
            severity = await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)
            assert severity == AlarmSeverity.NONE
