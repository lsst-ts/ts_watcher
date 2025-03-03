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
import unittest

import pytest
from lsst.ts import watcher
from lsst.ts.xml.enums.Watcher import AlarmSeverity

# Maximum time (seconds) to wait for the next severity to be reported.
NEXT_SEVERITY_TIMEOUT = 1


class TestTriggeredSeveritiesTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_basics(self):
        schema = watcher.rules.test.TriggeredSeverities.get_schema()
        assert schema is not None
        name = "arulename"
        severities = [AlarmSeverity.WARNING, AlarmSeverity.CRITICAL, AlarmSeverity.NONE]
        config = watcher.rules.test.TriggeredSeverities.make_config(
            name=name, severities=severities
        )
        assert config.repeats == 0  # The default value.

        desired_rule_name = f"test.TriggeredSeverities.{name}"
        rule = watcher.rules.test.TriggeredSeverities(config=config)
        assert rule.remote_info_list == []
        assert rule.name == desired_rule_name
        assert isinstance(rule.alarm, watcher.Alarm)
        assert rule.alarm.name == rule.name
        assert rule.alarm.nominal
        with pytest.raises(RuntimeError):
            await rule.update_alarm_severity()
        assert name in repr(rule)
        assert "test.TriggeredSeverities" in repr(rule)

    async def test_run(self):
        repeats = 2
        severities = [
            AlarmSeverity.WARNING,
            AlarmSeverity.CRITICAL,
            AlarmSeverity.WARNING,
            AlarmSeverity.SERIOUS,
            AlarmSeverity.NONE,
        ]
        config = watcher.rules.test.TriggeredSeverities.make_config(
            name="arbitrary",
            severities=severities,
            repeats=repeats,
        )
        assert config.repeats == 2
        rule = watcher.rules.test.TriggeredSeverities(config=config)

        expected_severities = severities * repeats
        read_severities = []

        alarm_seen_event = asyncio.Event()

        async def alarm_callback(alarm):
            nonlocal read_severities
            read_severities.append(alarm.severity)
            alarm_seen_event.set()

        rule.alarm.callback = alarm_callback
        rule.start()
        for i in range(len(expected_severities)):
            alarm_seen_event.clear()
            rule.trigger_next_severity_event.set()
            await asyncio.wait_for(
                alarm_seen_event.wait(), timeout=NEXT_SEVERITY_TIMEOUT
            )
        assert rule.run_task.done()
        rule.stop()
        assert read_severities == expected_severities
