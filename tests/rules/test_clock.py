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
import yaml

from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts import salobj
from lsst.ts import watcher

LONG_TIMEOUT = 60  # timeout for starting all watcher remotes (sec)


class HeartbeatWriter(salobj.topics.ControllerEvent):
    """A heartbeat event writer with incorrect private_sndStamp.
    """

    def __init__(self, salinfo):
        super().__init__(salinfo=salinfo, name="heartbeat")

    async def aput(self, dt):
        """Write a sample with ``private_sndStamp = current time + dt``.
        """
        self.data.private_sndStamp = salobj.current_tai() + dt
        self.data.private_revCode = self.rev_code
        self.data.private_origin = self.salinfo.domain.origin
        setattr(self.data, f"{self.salinfo.name}ID", self.salinfo.index)
        self._writer.write(self.data)
        await asyncio.sleep(0.001)

    def put(self):
        raise NotImplementedError()

    def set_put(self, *args, **kwargs):
        raise NotImplementedError()


class ClockTestCase(asynctest.TestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()

    def make_config(self, name, threshold):
        """Make a config for the Clock rule.

        Parameters
        ----------
        name : `str`
            CSC name and index in the form `name` or `name:index`.
            The default index is 0.
        threshold : `float`
            Maximum allowed time between heartbeat events (sec).
        """
        schema = watcher.rules.Clock.get_schema()
        validator = salobj.DefaultingValidator(schema)
        config_dict = dict(name=name, threshold=threshold)

        full_config_dict = validator.validate(config_dict)
        config = types.SimpleNamespace(**full_config_dict)
        for key in config_dict:
            self.assertEqual(getattr(config, key), config_dict[key])
        return config

    async def test_basics(self):
        schema = watcher.rules.Clock.get_schema()
        self.assertIsNotNone(schema)
        name = "ScriptQueue"
        threshold = 1.2
        config = self.make_config(name=name, threshold=threshold)
        desired_rule_name = f"Clock.{name}:0"

        rule = watcher.rules.Clock(config=config)
        self.assertEqual(rule.name, desired_rule_name)
        self.assertEqual(rule.threshold, threshold)
        self.assertIsInstance(rule.alarm, watcher.Alarm)
        self.assertEqual(rule.alarm.name, rule.name)
        self.assertTrue(rule.alarm.nominal)
        self.assertEqual(len(rule.remote_info_list), 1)
        remote_info = rule.remote_info_list[0]
        self.assertEqual(remote_info.name, name)
        self.assertEqual(remote_info.index, 0)
        self.assertIn(name, repr(rule))
        self.assertIn("Clock", repr(rule))

    async def test_call(self):
        name = "ScriptQueue"
        index = 5
        threshold = 0.5

        watcher_config_dict = yaml.safe_load(
            f"""
            disabled_sal_components: []
            auto_acknowledge_delay: 3600
            auto_unacknowledge_delay: 3600
            rules:
            - classname: Clock
              configs:
              - name: {name}:{index}
                threshold: {threshold}
            escalation: []
            """
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)

        async with salobj.Domain() as domain:
            salinfo = salobj.SalInfo(domain=domain, name=name, index=index)
            heartbeat_writer = HeartbeatWriter(salinfo=salinfo)
            async with watcher.Model(domain=domain, config=watcher_config) as model:
                model.enable()

                self.assertEqual(len(model.rules), 1)
                rule_name = f"Clock.{name}:{index}"
                rule = model.rules[rule_name]
                alarm = rule.alarm

                # Sending fewer than Clock.min_errors heartbeat events
                # with excessive error should leave the alarm in its
                # original nominal state, because we require
                # ``min_errors`` sequential time errors for an alarm.
                bad_dt = threshold + 0.1
                good_dt = threshold * 0.9
                for i in range(rule.min_errors - 1):
                    await heartbeat_writer.aput(dt=bad_dt)
                    self.assertTrue(alarm.nominal)

                # The next heartbeat event with bad dt should set
                # alarm severity to WARNING. The sign of the clock
                # error should not matter, so try a negative error.
                await heartbeat_writer.aput(dt=-bad_dt)
                self.assertFalse(alarm.nominal)
                self.assertEqual(alarm.severity, AlarmSeverity.WARNING)
                self.assertIn("mean", alarm.reason)

                # A valid value should return alarm severity to NONE.
                await heartbeat_writer.aput(dt=good_dt)
                self.assertEqual(alarm.severity, AlarmSeverity.NONE)

                # Sending fewer than Clock.min_errors heartbeat events
                # with excessive error should leave the alarm severity
                # at NONE
                for i in range(rule.min_errors - 1):
                    await heartbeat_writer.aput(dt=bad_dt)
                    self.assertEqual(alarm.severity, AlarmSeverity.NONE)

                await heartbeat_writer.aput(dt=bad_dt)
                self.assertFalse(alarm.nominal)
                self.assertEqual(alarm.severity, AlarmSeverity.WARNING)


if __name__ == "__main__":
    unittest.main()
