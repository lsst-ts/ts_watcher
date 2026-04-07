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


class HvacTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_test_topic_subname(randomize=True)
        self.remote_name = "HVAC"
        # TODO OSW-2079 Remove backward compatibility with XML v26.0.0
        self.component_info = ComponentInfo("HVAC", topic_subname="")
        if "tel_dynaleneP05" in self.component_info.topics:
            self.callback_name = "tel_dynaleneP05"
        else:
            self.callback_name = "tel_dynalene"
        self.rule_config_dict = {
            "rule_name": "Dynalene",
            "callback_names": [self.callback_name],
            "individual_limits": [
                {
                    "item_name": "dynCH01supTS05",
                    "limit_type": "upper",
                    "limit_value": 30.0,
                    "severity": AlarmSeverity.WARNING.name,
                },
                {
                    "item_name": "dynCH01supFS01",
                    "limit_type": "lower",
                    "limit_value": 10.0,
                    "time_span": 30.0,
                    "severity": AlarmSeverity.WARNING.name,
                },
            ],
            "difference_limits": [
                {
                    "first_item_name": "dynCH02supTS07",
                    "second_item_name": "dynCH01supFS01",
                    "limit_type": "lower",
                    "limit_value": 10.0,
                    "severity": AlarmSeverity.WARNING.name,
                },
                {
                    "first_item_name": "dynCH01supTS05",
                    "second_item_name": "dynCH02supFS02",
                    "limit_type": "lower",
                    "limit_value": 10.0,
                    "severity": AlarmSeverity.WARNING.name,
                },
                {
                    "first_item_name": "dynCH01supTS05",
                    "second_item_name": "dynCH02supFS02",
                    "limit_type": "upper",
                    "limit_value": 30.0,
                    "time_span": 30.0,
                    "severity": AlarmSeverity.WARNING.name,
                },
            ],
        }

    async def asyncTearDown(self) -> None:
        """Runs after each test is completed."""
        await salobj.delete_kafka_topics()

    async def test_constructor(self):
        schema = watcher.rules.Hvac.get_schema()
        assert schema is not None

        config = watcher.rules.Hvac.make_config(**self.rule_config_dict)
        rule = watcher.rules.Hvac(config=config)

        rule_name = "Dynalene"
        assert rule.name == f"{self.remote_name}.{rule_name}"
        assert isinstance(rule.alarm, watcher.Alarm)
        assert rule.alarm.name == rule.name
        assert rule.alarm.nominal
        assert len(rule.remote_info_list) == 1
        remote_info = rule.remote_info_list[0]
        assert remote_info.name == self.remote_name
        assert remote_info.index == 0
        assert rule_name in repr(rule)

    async def test_operation(self):
        config = self.rule_config_dict
        watcher_config_dict = dict(
            disabled_sal_components=[],
            auto_acknowledge_delay=3600,
            auto_unacknowledge_delay=3600,
            rules=[dict(classname="Hvac", configs=[config])],
            escalation=(),
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)
        async with (
            salobj.Controller(name=self.remote_name, index=0) as controller,
            watcher.Model(domain=controller.domain, config=watcher_config) as model,
        ):
            topic = getattr(controller, self.callback_name)

            rule = model.rules[f"{self.remote_name}.{config['rule_name']}"]
            rule.alarm.init_severity_queue()
            await model.enable()

            await watcher.write_and_wait(model, topic)
            total_num_rule_configs = 0
            if "individual_limits" in config:
                total_num_rule_configs += len(config["individual_limits"])
            if "difference_limits" in config:
                total_num_rule_configs += len(config["difference_limits"])
            assert len(rule.alarm_info_dict.keys()) == total_num_rule_configs

            # The CSC has sent data and exactly two WARNINGs will have been
            # raised because of the configured rules.
            severity = await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)
            assert severity == AlarmSeverity.WARNING
            assert rule.alarm.reason != ""
            assert "," in rule.alarm.reason
            reasons = rule.alarm.reason.split(",")
            assert len(reasons) == 2

    async def test_stale_value_detection(self):
        """Test detection of stale/unchanging values."""
        # TODO OSW-2079 Remove backward compatibility with XML v26.0.0
        if "tel_dynaleneP05" in self.component_info.topics:
            stale_config_dict = {
                "rule_name": "Dynalene",
                "callback_names": ["tel_dynaleneP05"],
                "stale_value_limits": [
                    {
                        "item_name": "dynCH01supTS05",
                        "num_samples": 3,
                        "severity": AlarmSeverity.SERIOUS.name,
                        "message": "HVAC value stuck - check sensors",
                    },
                    {
                        "item_name": "dynCH01supFS01",
                        "num_samples": 2,
                        "severity": AlarmSeverity.WARNING.name,
                    },
                ],
            }
        else:
            stale_config_dict = {
                "rule_name": "Dynalene",
                "callback_names": ["tel_dynalene"],
                "stale_value_limits": [
                    {
                        "item_name": "dynCH01supTS05",
                        "num_samples": 3,
                        "severity": AlarmSeverity.SERIOUS.name,
                        "message": "HVAC value stuck - check sensors",
                    },
                    {
                        "item_name": "dynCH01supFS01",
                        "num_samples": 2,
                        "severity": AlarmSeverity.WARNING.name,
                    },
                ],
            }
        watcher_config_dict = dict(
            disabled_sal_components=[],
            auto_acknowledge_delay=3600,
            auto_unacknowledge_delay=3600,
            rules=[dict(classname="Hvac", configs=[stale_config_dict])],
            escalation=(),
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)
        async with (
            salobj.Controller(name=self.remote_name, index=0) as controller,
            watcher.Model(domain=controller.domain, config=watcher_config) as model,
        ):
            rule = model.rules[f"{self.remote_name}.{stale_config_dict['rule_name']}"]
            rule.alarm.init_severity_queue()
            await model.enable()

            tel_topic = getattr(controller, self.callback_name)

            await watcher.write_and_wait(model, tel_topic)
            assert len(rule.alarm_info_dict.keys()) == 0
            assert rule.alarm.nominal

            await watcher.write_and_wait(model, tel_topic)

            severity = await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)
            assert severity == AlarmSeverity.NONE

            severity = await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)
            assert severity == AlarmSeverity.WARNING
            assert "dynCH01supFS01" in rule.alarm.reason

            await watcher.write_and_wait(model, tel_topic)
            await watcher.write_and_wait(model, tel_topic)

            severity = await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)
            assert severity == AlarmSeverity.SERIOUS
            assert "HVAC value stuck - check sensors" in rule.alarm.reason

            await watcher.write_and_wait(model, tel_topic, dynCH01supTS05=31.0)

            severity = await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)
            assert severity == AlarmSeverity.WARNING

            await watcher.write_and_wait(model, tel_topic, dynCH01supTS05=30.0, dynCH01supFS01=1.0)
            await watcher.write_and_wait(model, tel_topic, dynCH01supTS05=29.0, dynCH01supFS01=2.0)
            await watcher.write_and_wait(model, tel_topic, dynCH01supTS05=28.0, dynCH01supFS01=3.0)

            severity = await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)
            assert severity == AlarmSeverity.NONE
