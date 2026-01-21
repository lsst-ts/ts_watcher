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
import math
import types
import unittest

import pytest

from lsst.ts import salobj, watcher
from lsst.ts.xml.enums.Watcher import AlarmSeverity

STD_TIMEOUT = 5  # Max time to send/receive a topic (seconds)


class MTM1M3TemperatureTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        if hasattr(salobj, "set_random_topic_subname"):
            salobj.set_random_topic_subname()
        else:
            salobj.set_random_lsst_dds_partition_prefix()
        self.rule_config_dict = {
            "temperature_change_interval": 3600,
            "m1m3_temperature_difference_threshold": 5.0,
            "m1m3_temperature_change_threshold": 0.75,
        }
        self.log = logging.getLogger("MTM1M3Temperature")

    async def test_constructor(self):
        config = watcher.rules.MTM1M3Temperature.make_config(**self.rule_config_dict)
        rule = watcher.rules.MTM1M3Temperature(config=config, log=self.log)

        assert rule.name == "MTM1M3Temperature"
        assert isinstance(rule.alarm, watcher.Alarm)
        assert rule.alarm.name == rule.name
        assert rule.alarm.nominal
        assert len(rule.remote_info_list) == 2

    async def test_operation(self):
        watcher_config_dict = dict(
            disabled_sal_components=[],
            auto_acknowledge_delay=3600,
            auto_unacknowledge_delay=3600,
            rules=[dict(classname="MTM1M3Temperature", configs=[self.rule_config_dict])],
            escalation=(),
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)
        async with (
            salobj.Controller(name="MTDome", index=0) as mtdome,
            salobj.Controller(name="MTM1M3TS", index=0) as mtm1m3ts,
            watcher.Model(domain=mtdome.domain, config=watcher_config) as model,
        ):
            rule: watcher.rules.MTM1M3Temperature = model.rules["MTM1M3Temperature"]
            rule.alarm.init_severity_queue()
            await model.enable()

            # Make sure that the aperture shutter is open.
            await watcher.write_and_wait(
                model=model,
                topic=mtdome.tel_apertureShutter,
                positionActual=[10.0, 10.0],
            )
            # The alarm doesn't change so no new alarm raised.
            severity = await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)
            assert severity == AlarmSeverity.NONE

            # Now telemetry from the other systems can be sent that should
            # trigger or silence the alarm.
            test_data_items = [
                {
                    "topic": mtm1m3ts.tel_thermalData,
                    "items": {"absoluteTemperature": [15, 15, 17, 15] + [math.nan] * 92},
                    "expected_severity": AlarmSeverity.NONE,
                    "expected_reason": "",
                    "hour": 16,
                    "minute": 23,
                },
                {
                    "topic": mtm1m3ts.tel_thermalData,
                    "items": {"absoluteTemperature": [15, 15, 19, 15] + [math.nan] * 92},
                    "expected_severity": AlarmSeverity.SERIOUS,
                    "expected_reason": "M1M3 temperature change is too high and dome is open.",
                    "hour": 16,
                    "minute": 24,
                },
                {
                    "topic": mtm1m3ts.tel_thermalData,
                    "items": {"absoluteTemperature": [15, 15, 21, 15] + [math.nan] * 92},
                    "expected_severity": AlarmSeverity.SERIOUS,
                    "expected_reason": (
                        "M1M3 temperature change is too high, "
                        "M1M3 temperature difference is too high and dome is open."
                    ),
                    "hour": 16,
                    "minute": 25,
                },
            ]
            previous_severity = AlarmSeverity.NONE
            previous_reason = ""
            for test_data_item in test_data_items:
                await watcher.write_and_wait(
                    model=model,
                    topic=test_data_item["topic"],
                    timestamp=(test_data_item["hour"] * 60 + test_data_item["minute"]) * 60.0,
                    **test_data_item["items"],
                )
                if (
                    previous_severity == test_data_item["expected_severity"]
                    and previous_reason == test_data_item["expected_reason"]
                ):
                    with pytest.raises(TimeoutError):
                        severity = await asyncio.wait_for(
                            rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT
                        )
                else:
                    severity = await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)
                    assert severity == test_data_item["expected_severity"]
                    previous_severity = severity

                assert rule.alarm.reason == test_data_item["expected_reason"]
                previous_reason = rule.alarm.reason
