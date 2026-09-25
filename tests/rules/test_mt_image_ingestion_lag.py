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
from lsst.ts.xml.enums.Watcher import AlarmSeverity

STD_TIMEOUT = 1  # Max time to send/receive a topic (seconds)


class MTImageIngestionLagTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_test_topic_subname(randomize=True)
        self._image_sequence = 0
        self._date_string = datetime.datetime.now().strftime("%Y%m%d")

    async def asyncTearDown(self) -> None:
        """Runs after each test is completed."""
        await salobj.delete_kafka_topics()

    async def test_basics(self):
        schema = watcher.rules.MTImageIngestionLag.get_schema()
        assert schema is not None
        config = watcher.rules.MTImageIngestionLag.make_config()
        desired_rule_name = "MTImageIngestionLag"

        rule = watcher.rules.MTImageIngestionLag(config=config)
        assert rule.name == desired_rule_name
        assert isinstance(rule.alarm, watcher.Alarm)
        assert rule.alarm.name == rule.name
        assert rule.alarm.nominal
        assert len(rule.remote_info_list) == 2

        remote_info = rule.remote_info_list[0]
        assert remote_info.name == "MTOODS"
        assert remote_info.index == 0
        assert desired_rule_name in repr(rule)

        remote_info = rule.remote_info_list[1]
        assert remote_info.name == "MTCamera"
        assert remote_info.index == 0

    async def test_call(self):
        watcher_config_dict = dict(
            disabled_sal_components=[],
            auto_acknowledge_delay=3600,
            auto_unacknowledge_delay=3600,
            rules=[dict(classname="MTImageIngestionLag", configs=[{"serious_lag_threshold": None}])],
            escalation=(),
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)

        async with (
            salobj.Controller(name="MTOODS") as self.mtaos,
            salobj.Controller(name="MTCamera") as self.mtcamera,
            watcher.Model(domain=self.mtaos.domain, config=watcher_config) as self.model,
        ):
            await self.model.enable()

            assert len(self.model.rules) == 1
            rule_name = "MTImageIngestionLag"
            rule = self.model.rules[rule_name]
            rule.alarm.init_severity_queue()

            # Reset the rule.
            rule.current_severity = None
            rule.current_reason = None
            rule.mtaos_dof_visit_id = math.inf
            rule.camera_visit_id = math.inf

            await self.send_end_readout_event()
            await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)

            await self.send_image_in_oods_event()
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
            severity = await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)
            assert severity == AlarmSeverity.WARNING

            await self.send_image_in_oods_event()
            severity = await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)
            assert severity == AlarmSeverity.NONE

    async def send_closed_loop_state_event(self, state) -> None:
        topic = getattr(self.mtaos, "evt_closedLoopState")
        await watcher.write_and_wait(self.model, topic, state=state)

    async def send_image_in_oods_event(self) -> None:
        topic = getattr(self.mtaos, "evt_imageInOODS")
        obs_id = f"MC_0_{self._date_string}_{self._image_sequence:06d}"
        await watcher.write_and_wait(self.model, topic, obsid=obs_id)

    async def send_end_readout_event(self) -> None:
        topic = getattr(self.mtcamera, "evt_endReadout")
        self._image_sequence += 1
        await watcher.write_and_wait(
            self.model, topic, imageDate=self._date_string, imageNumber=self._image_sequence
        )
