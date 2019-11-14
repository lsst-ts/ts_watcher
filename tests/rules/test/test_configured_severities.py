# This file is part of ts_watcher.
#
# Developed for the LSST Data Management System.
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

import asynctest

from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts import salobj
from lsst.ts import watcher


class TestConfiguredSeveritiesTestCase(asynctest.TestCase):
    def make_config(self, name, interval, severities):
        """Make a config for the TestConfiguredSeverities rule.

        Parameters
        ----------
        name : `str`
            Rule name (one field in a longer name).
        interval : `float`
            Interval between severities (seconds).
        severities : `list` [`lsst.ts.idl.enums.Watcher.AlarmSeverity`]
            A list of severities.
        """
        schema = watcher.rules.test.ConfiguredSeverities.get_schema()
        validator = salobj.DefaultingValidator(schema)
        config_dict = dict(name=name,
                           interval=interval,
                           severities=severities)

        full_config_dict = validator.validate(config_dict)
        config = types.SimpleNamespace(**full_config_dict)
        for key in config_dict:
            self.assertEqual(getattr(config, key), config_dict[key])
        return config

    def test_basics(self):
        schema = watcher.rules.test.ConfiguredSeverities.get_schema()
        self.assertIsNotNone(schema)
        name = "arulename"
        interval = 1.23
        severities = [AlarmSeverity.WARNING,
                      AlarmSeverity.CRITICAL,
                      AlarmSeverity.NONE]
        config = self.make_config(name=name, interval=interval, severities=severities)
        desired_rule_name = f"test.ConfiguredSeverities.{name}"

        rule = watcher.rules.test.ConfiguredSeverities(config=config)
        self.assertEqual(rule.remote_info_list, [])
        self.assertEqual(rule.name, desired_rule_name)
        self.assertIsInstance(rule.alarm, watcher.Alarm)
        self.assertEqual(rule.alarm.name, rule.name)
        self.assertTrue(rule.alarm.nominal)
        with self.assertRaises(RuntimeError):
            rule(topic_callback=None)
        self.assertIn(name, repr(rule))
        self.assertIn("test.ConfiguredSeverities", repr(rule))

    async def test_run(self):
        interval = 0.01
        severities = [AlarmSeverity.WARNING,
                      AlarmSeverity.CRITICAL,
                      AlarmSeverity.WARNING,
                      AlarmSeverity.SERIOUS,
                      AlarmSeverity.NONE]
        config = self.make_config(name="arbitrary", interval=interval, severities=severities)
        rule = watcher.rules.test.ConfiguredSeverities(config=config)

        read_severities = []
        # Number of cycles of these severities to read; arbitrary
        # but should be > 1 to check that the severities repeat.
        num_cycles_to_read = 3
        num_events_to_read = num_cycles_to_read * len(severities)
        done_future = asyncio.Future()

        def alarm_callback(alarm):
            nonlocal read_severities
            read_severities.append(alarm.severity)
            if len(read_severities) >= num_events_to_read and not done_future.done():
                done_future.set_result(None)

        rule.alarm.callback = alarm_callback
        rule.start()
        await asyncio.wait_for(done_future, timeout=2)
        rule.stop()
        expected_severities = severities*num_cycles_to_read
        self.assertEqual(read_severities, expected_severities)


if __name__ == "__main__":
    unittest.main()
