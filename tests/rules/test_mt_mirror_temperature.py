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
from lsst.ts.watcher.rules import MTMirrorTemperature
from lsst.ts.xml.enums.Watcher import AlarmSeverity

STD_TIMEOUT = 5  # Max time to send/receive a topic (seconds)


class MTMirrorTemperatureTestCase(unittest.IsolatedAsyncioTestCase):

    def setUp(self) -> None:
        salobj.set_random_lsst_dds_partition_prefix()

    async def test_constructor(self) -> None:

        schema = watcher.rules.MTMirrorTemperature.get_schema()
        assert schema is not None

        rule = MTMirrorTemperature(None)
        assert len(rule.remote_info_list) == 1
        assert len(rule.remote_info_list[0].poll_names) == 1

    async def test_operation(self) -> None:
        watcher_config_dict = dict(
            disabled_sal_components=[],
            auto_acknowledge_delay=3600,
            auto_unacknowledge_delay=3600,
            rules=[dict(classname="MTMirrorTemperature", configs=[{}])],
            escalation=(),
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)

        async with salobj.Controller("MTM2", 0) as controller, watcher.Model(
            domain=controller.domain, config=watcher_config
        ) as model:

            rule_name = "MTMirrorTemperature.MTM2"
            rule = model.rules[rule_name]
            rule.alarm.init_severity_queue()

            await model.enable()

            # 12 ring temperature values and 2 intake temperature values
            normal_ring = [0.0] * 12
            normal_intake = [0.0] * 2

            gradient_ring = [0.0] * 12
            gradient_ring[0] = rule.config.gradient + 1.0
            test_data_items = [
                {
                    "topic": controller.tel_temperature,
                    "fields": {
                        "ring": normal_ring,
                        "intake": normal_intake,
                    },
                    "expected_severity": AlarmSeverity.NONE,
                },
                {
                    "topic": controller.tel_temperature,
                    "fields": {
                        "ring": normal_ring,
                        "intake": [rule.config.intake + 1.0] * 2,
                    },
                    "expected_severity": AlarmSeverity.WARNING,
                },
                {
                    "topic": controller.tel_temperature,
                    "fields": {
                        "ring": normal_ring,
                        "intake": normal_intake,
                    },
                    "expected_severity": AlarmSeverity.NONE,
                },
                {
                    "topic": controller.tel_temperature,
                    "fields": {
                        "ring": [rule.config.ring + 1.0] * 12,
                        "intake": normal_intake,
                    },
                    "expected_severity": AlarmSeverity.WARNING,
                },
                {
                    "topic": controller.tel_temperature,
                    "fields": {
                        "ring": normal_ring,
                        "intake": normal_intake,
                    },
                    "expected_severity": AlarmSeverity.NONE,
                },
                {
                    "topic": controller.tel_temperature,
                    "fields": {
                        "ring": gradient_ring,
                        "intake": normal_intake,
                    },
                    "expected_severity": AlarmSeverity.WARNING,
                },
                {
                    "topic": controller.tel_temperature,
                    "fields": {
                        "ring": normal_ring,
                        "intake": normal_intake,
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

            assert rule.alarm.severity_queue.empty()
