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
import types
import unittest

from lsst.ts import salobj, watcher
from lsst.ts.watcher.rules import MTDomeAzEnabled
from lsst.ts.xml.enums.MTDome import EnabledState
from lsst.ts.xml.enums.Watcher import AlarmSeverity

STD_TIMEOUT = 5  # Max time to send/receive a topic (seconds)


class MTDomeAzEnabledTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()

    async def test_constructor(self):
        rule = MTDomeAzEnabled(config=None)
        assert len(rule.remote_info_list) == 1

    async def test_operation(self):
        watcher_config_dict = dict(
            disabled_sal_components=[],
            auto_acknowledge_delay=3600,
            auto_unacknowledge_delay=3600,
            rules=[dict(classname="MTDomeAzEnabled", configs=[{}])],
            escalation=(),
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)
        async with salobj.Controller(
            name="MTDome", index=0
        ) as controller, watcher.Model(
            domain=controller.domain, config=watcher_config
        ) as model:
            test_data_items = [
                {
                    "topic": controller.evt_azEnabled,
                    "fault_code": "",
                    "expected_severity": AlarmSeverity.NONE,
                },
                {
                    "topic": controller.evt_azEnabled,
                    "fault_code": "Ethercat problem.",
                    "expected_severity": AlarmSeverity.CRITICAL,
                },
            ]

            rule_name = "MTDomeAzEnabled.MTDome"
            rule = model.rules[rule_name]
            rule.alarm.init_severity_queue()

            await model.enable()

            for data_item in test_data_items:
                await watcher.write_and_wait(
                    model=model,
                    topic=data_item["topic"],
                    state=EnabledState.ENABLED,
                    faultCode=data_item["fault_code"],
                )
                severity = await asyncio.wait_for(
                    rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT
                )
                assert severity == data_item["expected_severity"]
                assert rule.alarm.severity_queue.empty()
