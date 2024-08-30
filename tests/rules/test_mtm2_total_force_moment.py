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
from lsst.ts.watcher.rules import MTM2TotalForceMoment
from lsst.ts.xml.enums.Watcher import AlarmSeverity

STD_TIMEOUT = 5  # Max time to send/receive a topic (seconds)


class MTM2TotalForceMomentTestCase(unittest.IsolatedAsyncioTestCase):

    def setUp(self) -> None:
        salobj.set_random_lsst_dds_partition_prefix()

    async def test_constructor(self) -> None:

        schema = watcher.rules.MTM2TotalForceMoment.get_schema()
        assert schema is not None

        rule = MTM2TotalForceMoment(None)
        assert len(rule.remote_info_list) == 1
        assert len(rule.remote_info_list[0].poll_names) == 2

    async def test_operation(self) -> None:
        watcher_config_dict = dict(
            disabled_sal_components=[],
            auto_acknowledge_delay=3600,
            auto_unacknowledge_delay=3600,
            rules=[dict(classname="MTM2TotalForceMoment", configs=[{}])],
            escalation=(),
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)

        async with salobj.Controller("MTM2", 0) as controller, watcher.Model(
            domain=controller.domain, config=watcher_config
        ) as model:

            rule_name = "MTM2TotalForceMoment.MTM2"
            rule = model.rules[rule_name]
            rule.alarm.init_severity_queue()

            await model.enable()

            value_normal = 10.0
            test_data_items = [
                {
                    "topic": controller.tel_netForcesTotal,
                    "fields": {
                        "fx": value_normal,
                        "fy": value_normal,
                        "fz": value_normal,
                    },
                    "expected_severity": AlarmSeverity.NONE,
                },
                {
                    "topic": controller.tel_netForcesTotal,
                    "fields": {
                        "fx": value_normal,
                        "fy": rule.config.fy + 1.0,
                        "fz": value_normal,
                    },
                    "expected_severity": AlarmSeverity.SERIOUS,
                },
                {
                    "topic": controller.tel_netForcesTotal,
                    "fields": {
                        "fx": value_normal,
                        "fy": value_normal,
                        "fz": value_normal,
                    },
                    "expected_severity": AlarmSeverity.NONE,
                },
                {
                    "topic": controller.tel_netMomentsTotal,
                    "fields": {
                        "mx": value_normal,
                        "my": value_normal,
                        "mz": -rule.config.mz - 1.0,
                    },
                    "expected_severity": AlarmSeverity.SERIOUS,
                },
                {
                    "topic": controller.tel_netMomentsTotal,
                    "fields": {
                        "mx": value_normal,
                        "my": value_normal,
                        "mz": value_normal,
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
