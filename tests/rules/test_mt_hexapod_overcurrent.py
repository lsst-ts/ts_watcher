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
from lsst.ts.watcher.rules import MTCameraHexapodOvercurrent
from lsst.ts.xml.enums.MTHexapod import SalIndex
from lsst.ts.xml.enums.Watcher import AlarmSeverity

STD_TIMEOUT = 5  # Max time to send/receive a topic (seconds)


class MTHexapodOvercurrentTestCase(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()

    async def test_constructor(self):

        schema = MTCameraHexapodOvercurrent.get_schema()
        assert schema is not None

        rule = MTCameraHexapodOvercurrent(None)
        assert len(rule.remote_info_list) == 1
        assert len(rule.remote_info_list[0].callback_names) == 2

    async def test_operation(self):

        await self._test_operation(
            "MTCameraHexapodOvercurrent", SalIndex.CAMERA_HEXAPOD
        )
        await self._test_operation("MTM2HexapodOvercurrent", SalIndex.M2_HEXAPOD)

    async def _test_operation(self, classname: str, sal_index: SalIndex):
        watcher_config_dict = dict(
            disabled_sal_components=[],
            auto_acknowledge_delay=3600,
            auto_unacknowledge_delay=3600,
            rules=[dict(classname=classname, configs=[{}])],
            escalation=(),
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)

        async with salobj.Controller(
            "MTHexapod", sal_index.value
        ) as controller, watcher.Model(
            domain=controller.domain, config=watcher_config
        ) as model:
            rule_name = f"{classname}.MTHexapod"
            rule = model.rules[rule_name]
            rule.alarm.init_severity_queue()

            rule.config.max_count = 2

            await model.enable()

            motor_current = [5.0] + [1.0] * 5

            test_data_items = [
                {
                    "topic": controller.evt_controllerState,
                    "fields": {
                        "controllerState": 2,
                        "enabledSubstate": 0,
                    },
                    "expected_severity": AlarmSeverity.NONE,
                },
                {
                    "topic": controller.tel_electrical,
                    "fields": {
                        "motorCurrent": motor_current,
                    },
                },
                {
                    "topic": controller.tel_electrical,
                    "fields": {
                        "motorCurrent": motor_current,
                    },
                    "expected_severity": AlarmSeverity.WARNING,
                },
                {
                    "topic": controller.evt_controllerState,
                    "fields": {
                        "controllerState": 2,
                        "enabledSubstate": 1,
                    },
                    "expected_severity": AlarmSeverity.NONE,
                },
            ]

            for data_item in test_data_items:
                await data_item["topic"].set_write(**data_item["fields"])

                if "expected_severity" in data_item.keys():
                    severity = await asyncio.wait_for(
                        rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT
                    )
                    assert severity == data_item["expected_severity"]
