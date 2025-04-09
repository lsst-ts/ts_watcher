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

import asyncio
import logging
import types
import unittest

from lsst.ts import salobj, watcher
from lsst.ts.xml.enums.Watcher import AlarmSeverity

STD_TIMEOUT = 5  # Max time to send/receive a topic (seconds)


class MTM1M3ThermalFansTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_test_topic_subname()
        self.log = logging.getLogger("MTM1M3ThermalFans")

    async def test_constructor(self):
        rule = watcher.rules.MTM1M3ThermalFans(config=None, log=self.log)

        assert rule.name == "MTM1M3ThermalFans"
        assert isinstance(rule.alarm, watcher.Alarm)
        assert rule.alarm.name == rule.name
        assert rule.alarm.nominal
        assert len(rule.remote_info_list) == 1

    async def test_operation(self):
        watcher_config_dict = dict(
            disabled_sal_components=[],
            auto_acknowledge_delay=3600,
            auto_unacknowledge_delay=3600,
            rules=[dict(classname="MTM1M3ThermalFans", configs=[{}])],
            escalation=(),
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)
        async with (
            salobj.Controller(name="MTM1M3TS", index=0) as mtm1m3ts,
            watcher.Model(domain=mtm1m3ts.domain, config=watcher_config) as model,
        ):
            rule: watcher.rules.MTM1M3ThermalFans = model.rules["MTM1M3ThermalFans"]
            rule.alarm.init_severity_queue()
            await model.enable()

            test_data_items = [
                {
                    "topic": mtm1m3ts.tel_thermalData,
                    "items": {"fanRPM": [15.0, 15.0, 17.0, 15.0] + [100.0] * 92},
                    "expected_severity": AlarmSeverity.NONE,
                    "expected_reason": "",
                },
                {
                    "topic": mtm1m3ts.tel_thermalData,
                    "items": {"fanRPM": [15.0, 15.0, 0.0, 15.0] + [100.0] * 92},
                    "expected_severity": AlarmSeverity.WARNING,
                    "expected_reason": "Fans off indices: [2].",
                },
                {
                    "topic": mtm1m3ts.tel_thermalData,
                    "items": {"fanRPM": [0.0, 15.0, 0.0, 15.0] + [100.0] * 92},
                    "expected_severity": AlarmSeverity.WARNING,
                    "expected_reason": "Fans off indices: [0 2].",
                },
            ]
            for test_data_item in test_data_items:
                await watcher.write_and_wait(
                    model=model,
                    topic=test_data_item["topic"],
                    **test_data_item["items"],
                )
                severity = await asyncio.wait_for(
                    rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT
                )
                assert severity == test_data_item["expected_severity"]
                assert rule.alarm.severity_queue.empty()
