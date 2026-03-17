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


class MTM1M3EGWFlowTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_test_topic_subname()
        self.log = logging.getLogger("MTM1M3EGWFlow")

    async def test_constructor(self):
        rule = watcher.rules.MTM1M3EGWFlow(config=None, log=self.log)

        assert rule.name == "MTM1M3EGWFlow"
        assert isinstance(rule.alarm, watcher.Alarm)
        assert rule.alarm.name == rule.name
        assert rule.alarm.nominal
        assert len(rule.remote_info_list) == 1

    async def test_operation(self):
        watcher_config_dict = dict(
            disabled_sal_components=[],
            auto_acknowledge_delay=3600,
            auto_unacknowledge_delay=3600,
            rules=[dict(classname="MTM1M3EGWFlow", configs=[{"alarm_delay": 1}])],
            escalation=(),
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)
        async with (
            salobj.Controller(name="MTM1M3TS", index=0) as mtm1m3ts,
            watcher.Model(domain=mtm1m3ts.domain, config=watcher_config) as model,
        ):
            rule: watcher.rules.MTM1M3EGWFlow = model.rules["MTM1M3EGWFlow"]
            rule.alarm.init_severity_queue()

            await model.enable()

            test_data_items = [
                {
                    "topic": mtm1m3ts.tel_flowMeter,
                    "items": {"flowRate": 110, "private_sndStamp": 0},
                    "expected_severity": AlarmSeverity.NONE,
                    "expected_reason": "",
                },
                {
                    "topic": mtm1m3ts.evt_summaryState,
                    "items": {"summaryState": salobj.State.ENABLED},
                    "expected_severity": AlarmSeverity.NONE,
                    "expected_reason": "",
                },
                {
                    "topic": mtm1m3ts.evt_engineeringMode,
                    "items": {"engineeringMode": False},
                    "expected_severity": AlarmSeverity.NONE,
                    "expected_reason": "",
                },
                {
                    "topic": mtm1m3ts.tel_flowMeter,
                    "items": {"flowRate": 110},
                    "expected_severity": AlarmSeverity.NONE,
                    "expected_reason": "",
                },
                {
                    "topic": mtm1m3ts.tel_flowMeter,
                    "items": {"flowRate": 10},
                    "expected_severity": AlarmSeverity.NONE,
                    "expected_reason": "",
                },
                {
                    "topic": mtm1m3ts.tel_flowMeter,
                    "delay": 2,
                    "items": {"flowRate": 11},
                    "expected_severity": AlarmSeverity.WARNING,
                    "expected_reason": "Low flow rate: 11.00, minimum is 100.00",
                },
                {
                    "topic": mtm1m3ts.tel_flowMeter,
                    "items": {"flowRate": 110},
                    "expected_severity": AlarmSeverity.NONE,
                    "expected_reason": "",
                },
            ]

            severity = None

            for test_data_item in test_data_items:
                if "delay" in test_data_item.keys():
                    await asyncio.sleep(test_data_item["delay"])

                await watcher.write_and_wait(
                    model=model,
                    topic=test_data_item["topic"],
                    **test_data_item["items"],
                )
                if severity != test_data_item["expected_severity"]:
                    severity = await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)
                    assert severity == test_data_item["expected_severity"]
                    if severity != AlarmSeverity.NONE:
                        assert rule.alarm.reason == test_data_item["expected_reason"]

                assert rule.alarm.severity_queue.empty()
