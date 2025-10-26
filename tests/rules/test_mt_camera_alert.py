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

from lsst.ts import salobj, utils, watcher
from lsst.ts.xml.enums.Watcher import AlarmSeverity

STD_TIMEOUT = 5  # Max time to send/receive a topic (seconds)


class MTCameraAlertTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_test_topic_subname(randomize=True)
        self.remote_name = "MTCamera"
        self.rule_name = f"MTCameraAlert.{self.remote_name}.evt_alertRaised"
        self.rule_config_dict = {}

    async def test_constructor(self):
        schema = watcher.rules.MTCameraAlert.get_schema()
        assert schema is None

        config = watcher.rules.MTCameraAlert.make_config(**self.rule_config_dict)
        rule = watcher.rules.MTCameraAlert(config=config)

        assert rule.name == self.rule_name
        assert isinstance(rule.alarm, watcher.Alarm)
        assert rule.alarm.name == rule.name
        assert rule.alarm.nominal
        assert len(rule.remote_info_list) == 1
        remote_info = rule.remote_info_list[0]
        assert remote_info.name == self.remote_name
        assert remote_info.index == 0
        assert self.rule_name in repr(rule)

    async def test_operation(self):
        watcher_config_dict = dict(
            disabled_sal_components=[],
            auto_acknowledge_delay=3600,
            auto_unacknowledge_delay=3600,
            rules=[dict(classname="MTCameraAlert", configs=[{}])],
            escalation=(),
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)
        async with (
            salobj.Controller(name=self.remote_name, index=0) as controller,
            watcher.Model(domain=controller.domain, config=watcher_config) as model,
        ):
            rule = model.rules[self.rule_name]
            rule.alarm.init_severity_queue()
            await model.enable()

            alert_id = "TestId"
            description = "A test alert"
            cause = "Test cause"
            origin = "lsstcam"
            additional_info = "AdditionalInfo"

            for is_cleared in [False, True]:
                telemetry = {
                    "timestampAlertStatusChanged": utils.current_tai(),
                    "alertId": alert_id,
                    "description": description,
                    "currentSeverity": watcher.rules.CameraSeverity.ALARM,
                    "highestSeverity": watcher.rules.CameraSeverity.WARNING,
                    "isCleared": is_cleared,
                    "cause": cause,
                    "origin": origin,
                    "additionalInfo": additional_info,
                }
                await watcher.write_and_wait(model, controller.evt_alertRaised, **telemetry)

                severity = await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)
                if not is_cleared:
                    assert severity == AlarmSeverity.CRITICAL
                    assert rule.alarm.reason != ""
                    assert alert_id in rule.alarm.reason
                    assert description in rule.alarm.reason
                    assert cause in rule.alarm.reason
                    assert origin in rule.alarm.reason
                    assert additional_info in rule.alarm.reason
                else:
                    assert severity == AlarmSeverity.NONE
