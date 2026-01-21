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

import numpy as np

from lsst.ts import salobj, watcher
from lsst.ts.watcher.rules import MTTangentLinkTemperature
from lsst.ts.xml.enums.Watcher import AlarmSeverity

STD_TIMEOUT = 5  # Max time to send/receive a topic (seconds)


class MTTangentLinkTemperatureTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        salobj.set_random_lsst_dds_partition_prefix()

    async def test_constructor(self) -> None:
        schema = watcher.rules.MTTangentLinkTemperature.get_schema()
        assert schema is not None

        rule = MTTangentLinkTemperature(None)
        assert len(rule.remote_info_list) == 2
        assert len(rule.remote_info_list[0].poll_names) == 1
        assert len(rule.remote_info_list[1].poll_names) == 1

    async def test_operation(self) -> None:
        watcher_config_dict = dict(
            disabled_sal_components=[],
            auto_acknowledge_delay=3600,
            auto_unacknowledge_delay=3600,
            rules=[dict(classname="MTTangentLinkTemperature", configs=[{}])],
            escalation=(),
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)

        # 106 is the ESS SAL index for the M2 tangent link temperature
        async with (
            salobj.Controller("ESS", 106) as controller_ess,
            salobj.Controller("MTM2", 0) as controller_m2,
            watcher.Model(domain=controller_ess.domain, config=watcher_config) as model,
        ):
            rule_name = "MTTangentLinkTemperature.ESS"
            rule = model.rules[rule_name]
            rule.alarm.init_severity_queue()

            await model.enable()

            # 12 ring temperature values and 16 tangent link temperature
            # channels in ESS (but only 6 are used).
            tangent_normal = [np.nan] * 16
            tangent_normal[1:7] = [0.0] * 6

            tangent_bad = [np.nan] * 16
            tangent_bad[1:4] = [rule.config.buffer + 3.0 - idx for idx in range(3)]
            tangent_bad[4:7] = [0.0] * 3

            test_data_items = [
                {
                    "topic": controller_m2.tel_temperature,
                    "fields": {
                        "ring": [0.0] * 12,
                    },
                    "expected_severity": AlarmSeverity.NONE,
                },
                {
                    "topic": controller_ess.tel_temperature,
                    "fields": {
                        "temperatureItem": tangent_normal,
                    },
                },
                {
                    "topic": controller_ess.tel_temperature,
                    "fields": {
                        "temperatureItem": tangent_bad,
                    },
                    "expected_severity": AlarmSeverity.WARNING,
                },
                {
                    "topic": controller_ess.tel_temperature,
                    "fields": {
                        "temperatureItem": tangent_normal,
                    },
                    "expected_severity": AlarmSeverity.NONE,
                },
            ]

            for data_item in test_data_items:
                await data_item["topic"].set_write(**data_item["fields"])

                if "expected_severity" in data_item.keys():
                    severity = await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)
                    assert severity == data_item["expected_severity"]

    async def test_operation_timeout(self) -> None:
        watcher_config_dict = dict(
            disabled_sal_components=[],
            auto_acknowledge_delay=3600,
            auto_unacknowledge_delay=3600,
            rules=[dict(classname="MTTangentLinkTemperature", configs=[{"timeout": 0.5}])],
            escalation=(),
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)

        # 106 is the ESS SAL index for the M2 tangent link temperature
        async with (
            salobj.Controller("ESS", 106) as controller_ess,
            salobj.Controller("MTM2", 0) as _,
            watcher.Model(domain=controller_ess.domain, config=watcher_config) as model,
        ):
            rule_name = "MTTangentLinkTemperature.ESS"
            rule = model.rules[rule_name]
            rule.alarm.init_severity_queue()

            await model.enable()

            severity_timeout = await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)

            assert severity_timeout == AlarmSeverity.WARNING

            assert rule.alarm.severity_queue.empty()
