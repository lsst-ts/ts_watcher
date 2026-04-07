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
from lsst.ts.xml.component_info import ComponentInfo
from lsst.ts.xml.enums.Watcher import AlarmSeverity

STD_TIMEOUT = 5  # Max time to send/receive a topic (seconds)


class GenericBooleanTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_test_topic_subname(randomize=True)
        # TODO OSW-2079 Remove backward compatibility with XML v26.0.0
        self.component_info = ComponentInfo("HVAC", topic_subname="")
        if "evt_chiller01P01" in self.component_info.topics:
            self.callback_name = "evt_chiller01P01"
        else:
            self.callback_name = "evt_coldGlycolChiller01"
        self.remote_name = "HVAC"
        self.rule_config_dict = {
            "rule_name": "HVAC_chiller01",
            "remote_name": "HVAC",
            "remote_index": 0,
            "callback_name": self.callback_name,
            "alarm_items": [
                {"item_name": "alarmDevice", "alarm_value": True},
                {"item_name": "compressor1StatusAlarmActive", "alarm_value": True},
            ],
            "severity": "CRITICAL",
        }

    async def asyncTearDown(self) -> None:
        """Runs after each test is completed."""
        await salobj.delete_kafka_topics()

    async def test_constructor(self):
        schema = watcher.rules.GenericBoolean.get_schema()
        assert schema is not None

        config = watcher.rules.GenericBoolean.make_config(**self.rule_config_dict)
        rule = watcher.rules.GenericBoolean(config=config)

        rule_name = f"HVAC_chiller01.HVAC.{self.callback_name}"
        assert rule.name == rule_name
        assert isinstance(rule.alarm, watcher.Alarm)
        assert rule.alarm.name == rule.name
        assert rule.alarm.nominal
        assert len(rule.remote_info_list) == 1
        remote_info = rule.remote_info_list[0]
        assert remote_info.name == self.remote_name
        assert remote_info.index == 0
        assert rule_name in repr(rule)

    async def test_alarms(self):
        config = self.rule_config_dict
        watcher_config_dict = dict(
            disabled_sal_components=[],
            auto_acknowledge_delay=3600,
            auto_unacknowledge_delay=3600,
            rules=[dict(classname="GenericBoolean", configs=[config])],
            escalation=(),
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)
        async with (
            salobj.Controller(name=self.remote_name, index=0) as controller,
            watcher.Model(domain=controller.domain, config=watcher_config) as model,
        ):
            rule = model.rules[f"HVAC_chiller01.HVAC.{self.callback_name}"]
            rule.alarm.init_severity_queue()
            await model.enable()

            topic = getattr(controller, self.callback_name)

            for value in [True, False]:
                await watcher.write_and_wait(
                    model=model, topic=topic, alarmDevice=value, compressor1StatusAlarmActive=False
                )
                severity = await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)
                if value:
                    assert severity == AlarmSeverity.CRITICAL
                    assert rule.alarm.reason != ""
                else:
                    assert severity == AlarmSeverity.NONE
