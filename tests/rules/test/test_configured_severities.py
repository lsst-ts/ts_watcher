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


class TestConfiguredSeveritiesTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_basics(self):
        schema = watcher.rules.test.ConfiguredSeverities.get_schema()
        assert schema is not None
        name = "arulename"
        interval = 1.23
        severities = [AlarmSeverity.WARNING, AlarmSeverity.CRITICAL, AlarmSeverity.NONE]
        config = watcher.rules.test.ConfiguredSeverities.make_config(
            name=name, interval=interval, severities=severities
        )
        # Check default config parameters
        assert config.delay == 0
        assert config.repeats == 0

        desired_rule_name = f"test.ConfiguredSeverities.{name}"
        rule = watcher.rules.test.ConfiguredSeverities(config=config)
        assert rule.remote_info_list == []
        assert rule.name == desired_rule_name
        assert isinstance(rule.alarm, watcher.Alarm)
        assert rule.alarm.name == rule.name
        assert rule.alarm.nominal
        with pytest.raises(RuntimeError):
            await rule.update_alarm_severity()
        assert name in repr(rule)
        assert "test.ConfiguredSeverities" in repr(rule)

    async def test_run(self):
        interval = 0.01
        repeats = 2
        severities = [
            AlarmSeverity.WARNING,
            AlarmSeverity.CRITICAL,
            AlarmSeverity.WARNING,
            AlarmSeverity.SERIOUS,
            AlarmSeverity.NONE,
        ]
        config = watcher.rules.test.ConfiguredSeverities.make_config(
            name="arbitrary",
            interval=interval,
            severities=severities,
            delay=0.1,
            repeats=repeats,
        )
        assert config.delay == 0.1
        assert config.repeats == 2
        rule = watcher.rules.test.ConfiguredSeverities(config=config)

        expected_severities = severities * repeats
        read_severities = []
        num_expected_severities = len(expected_severities)
        done_future = asyncio.Future()

        async def alarm_callback(alarm):
            read_severities.append(alarm.severity)
            if len(read_severities) >= num_expected_severities and not done_future.done():
                done_future.set_result(None)

        rule.alarm.callback = alarm_callback
        rule.start()
        await asyncio.wait_for(done_future, timeout=NEXT_SEVERITY_TIMEOUT * num_expected_severities)
        # The rule's run_task should be done, or almost done.
        await asyncio.wait_for(rule.run_task, timeout=NEXT_SEVERITY_TIMEOUT)
        rule.stop()
        assert read_severities == expected_severities
