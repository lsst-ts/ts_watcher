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
import datetime
import math
import types
import unittest

from lsst.ts import salobj, watcher
from lsst.ts.xml.enums.MTAOS import ClosedLoopState
from lsst.ts.xml.enums.Watcher import AlarmSeverity

STD_TIMEOUT = 1  # Max time to send/receive a topic (seconds)


class MTAOSLagTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_test_topic_subname(randomize=True)
        self._image_sequence = 0
        self._date_string = datetime.datetime.now().strftime("%Y%m%d")

    async def asyncTearDown(self) -> None:
        """Runs after each test is completed."""
        await salobj.delete_kafka_topics()

    async def test_basics(self):
        schema = watcher.rules.MTAOSLag.get_schema()
        assert schema is not None
        config = watcher.rules.MTAOSLag.make_config()
        desired_rule_name = "MTAOSLag"

        rule = watcher.rules.MTAOSLag(config=config)
        assert rule.name == desired_rule_name
        assert isinstance(rule.alarm, watcher.Alarm)
        assert rule.alarm.name == rule.name
        assert rule.alarm.nominal
        assert len(rule.remote_info_list) == 2
        remote_info = rule.remote_info_list[0]
        assert remote_info.name == "MTAOS"
        assert remote_info.index == 0
        assert desired_rule_name in repr(rule)

    async def test_call(self):
        watcher_config_dict = dict(
            disabled_sal_components=[],
            auto_acknowledge_delay=3600,
            auto_unacknowledge_delay=3600,
            rules=[dict(classname="MTAOSLag", configs=[{"serious_lag_threshold": None}])],
            escalation=(),
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)

        # Test both when in closed loop and when not. Alarms should only be
        # raised when in closed loop.
        for state in {ClosedLoopState.WAITING_IMAGE, ClosedLoopState.IDLE}:
            with self.subTest(state=state):
                async with (
                    salobj.Controller(name="MTAOS") as self.mtaos,
                    salobj.Controller(name="MTCamera") as self.mtcamera,
                    watcher.Model(domain=self.mtaos.domain, config=watcher_config) as self.model,
                ):
                    await self.model.enable()

                    assert len(self.model.rules) == 1
                    rule_name = "MTAOSLag"
                    rule = self.model.rules[rule_name]
                    rule.alarm.init_severity_queue()

                    # Reset the rule.
                    rule.current_severity = None
                    rule.current_reason = None
                    rule.mtaos_dof_visit_id = math.inf
                    rule.camera_visit_id = math.inf

                    await self.send_closed_loop_state_event(state=state)
                    severity = await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)
                    assert severity == AlarmSeverity.NONE

                    await self.send_end_readout_event()
                    # No changes, so a timeout happens.
                    with self.assertRaises(TimeoutError):
                        await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)

                    await self.send_dof_event()
                    # No changes, so a timeout happens.
                    with self.assertRaises(TimeoutError):
                        await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)

                    # Send one endReadout event less because after this
                    # for-loop an endReaout event is sent that triggers the
                    # alarm.
                    for i in range(rule.warning_lag_threshold - 1):
                        await self.send_end_readout_event()
                        # No changes, so a timeout happens.
                        with self.assertRaises(TimeoutError):
                            await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)

                    await self.send_end_readout_event()
                    if state == ClosedLoopState.WAITING_IMAGE:
                        severity = await asyncio.wait_for(
                            rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT
                        )
                        assert severity == AlarmSeverity.WARNING
                    else:
                        with self.assertRaises(TimeoutError):
                            await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)

                    await self.send_dof_event()
                    if state == ClosedLoopState.WAITING_IMAGE:
                        severity = await asyncio.wait_for(
                            rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT
                        )
                        assert severity == AlarmSeverity.NONE
                    else:
                        with self.assertRaises(TimeoutError):
                            await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)

    async def send_closed_loop_state_event(self, state) -> None:
        topic = getattr(self.mtaos, "evt_closedLoopState")
        await watcher.write_and_wait(self.model, topic, state=state)

    async def send_dof_event(self) -> None:
        topic = getattr(self.mtaos, "evt_degreeOfFreedom")
        visit_id = int(self._date_string) * 1e5 + self._image_sequence
        await watcher.write_and_wait(self.model, topic, visitId=visit_id)

    async def send_end_readout_event(self) -> None:
        topic = getattr(self.mtcamera, "evt_endReadout")
        self._image_sequence += 1
        await watcher.write_and_wait(
            self.model, topic, imageDate=self._date_string, imageNumber=self._image_sequence
        )
