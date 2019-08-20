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
import yaml

from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts import salobj
from lsst.ts import watcher


class GetRuleClassTestCase(unittest.TestCase):
    def test_good_names(self):
        for classname, desired_class in (
            ("Enabled", watcher.rules.Enabled),
            ("test.NoConfig", watcher.rules.test.NoConfig),
            ("test.ConfiguredSeverities", watcher.rules.test.ConfiguredSeverities),
        ):
            rule_class = watcher.get_rule_class(classname)
            self.assertEqual(rule_class, desired_class)

    def test_bad_names(self):
        for bad_name in (
            "NoSuchRule",  # no such rule
            "test.NoSuchRule",  # no such rule
            "test.Enabled",  # wrong module
            "NoConfig",  # wrong module
            "test_NoConfig",  # wrong separator
        ):
            with self.assertRaises(ValueError):
                watcher.get_rule_class(bad_name)


class OneEnabledRuleHarness:
    """Make a Model with a single Enabled rule.

    Parameters
    ----------
    name : `str`
        Name of CSC to monitor
    index : `int`
        Index of CSC to monitor
    """
    def __init__(self, name="ScriptQueue", index=5):
        self.name = name
        self.index = index

        watcher_config_dict = yaml.safe_load(f"""
            disabled_sal_components: []
            rules:
            - classname: Enabled
              configs:
              - name: {name}:{index}
            """)
        watcher_config = types.SimpleNamespace(**watcher_config_dict)

        self.read_severities = []
        self.read_max_severities = []

        self.controller = salobj.Controller(name=name, index=index)
        self.model = watcher.Model(domain=self.controller.domain,
                                   config=watcher_config,
                                   alarm_callback=self.alarm_callback)

        rule_name = f"Enabled.{name}:{index}"
        self.rule = self.model.rules[rule_name]

    def alarm_callback(self, alarm):
        self.read_severities.append(alarm.severity)
        self.read_max_severities.append(alarm.max_severity)

    async def write_states(self, states):
        """Write a sequence of summary states.
        """
        for state in states:
            self.controller.evt_summaryState.set_put(summaryState=state, force_output=True)
            # give the remote a chance to read the data
            await asyncio.sleep(0.001)

    async def __aenter__(self):
        await asyncio.gather(self.controller.start_task,
                             self.model.start_task)
        return self

    async def __aexit__(self, *args):
        await self.model.close()
        await self.controller.close()


class ModelTestCase(unittest.TestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_domain()

    def test_acknowledge_alarm(self):
        async def doit():
            user = "test_ack_alarm"

            async with OneEnabledRuleHarness() as harness:

                harness.model.enable()
                await harness.model.enable_task

                self.assertTrue(harness.rule.alarm.nominal)
                self.assertFalse(harness.rule.alarm.acknowledged)

                await harness.write_states([salobj.State.STANDBY])

                self.assertFalse(harness.rule.alarm.nominal)
                self.assertEqual(harness.rule.alarm.severity, AlarmSeverity.WARNING)
                self.assertEqual(harness.rule.alarm.max_severity, AlarmSeverity.WARNING)

                harness.model.acknowledge_alarm(name=harness.rule.name,
                                                severity=AlarmSeverity.WARNING,
                                                user=user)
                self.assertTrue(harness.rule.alarm.acknowledged)
                self.assertEqual(harness.rule.alarm.acknowledged_by, user)

        asyncio.new_event_loop().run_until_complete(doit())

    def test_enable(self):
        async def doit():
            async with OneEnabledRuleHarness() as harness:

                self.assertEqual(len(harness.model.rules), 1)

                # Enable the model and write ENABLED several times.
                # This triggers the rule callback but that does not
                # change the state of the alarm.
                harness.model.enable()
                await harness.model.enable_task
                await harness.write_states((salobj.State.ENABLED,
                                            salobj.State.ENABLED,
                                            salobj.State.ENABLED))

                self.assertTrue(harness.rule.alarm.nominal)
                self.assertEqual(harness.read_severities, [])

                # Disable the model and issue several events that would
                # trigger an alarm if the model was enabled. Since the
                # model is disabled the alarm does not change states.
                harness.model.disable()
                await harness.write_states((salobj.State.FAULT,
                                            salobj.State.STANDBY))
                self.assertTrue(harness.rule.alarm.nominal)
                self.assertEqual(harness.read_severities, [])
                self.assertEqual(harness.read_max_severities, [])

                # Enable the model. This will trigger a callback with
                # the current state of the event (STANDBY).
                # Note that the earlier FAULT event is is ignored
                # because it arrived while disabled.
                harness.model.enable()
                await harness.model.enable_task
                self.assertFalse(harness.rule.alarm.nominal)
                self.assertEqual(harness.rule.alarm.severity, AlarmSeverity.WARNING)
                self.assertEqual(harness.rule.alarm.max_severity, AlarmSeverity.WARNING)
                self.assertEqual(harness.read_severities, [AlarmSeverity.WARNING])
                self.assertEqual(harness.read_max_severities, [AlarmSeverity.WARNING])

                # Issue more events; they should be processed normally.
                await harness.write_states((salobj.State.FAULT,
                                            salobj.State.STANDBY))
                self.assertFalse(harness.rule.alarm.nominal)
                self.assertEqual(harness.rule.alarm.severity, AlarmSeverity.WARNING)
                self.assertEqual(harness.rule.alarm.max_severity, AlarmSeverity.SERIOUS)
                self.assertEqual(harness.read_severities, [AlarmSeverity.WARNING,
                                                           AlarmSeverity.SERIOUS,
                                                           AlarmSeverity.WARNING])
                self.assertEqual(harness.read_max_severities, [AlarmSeverity.WARNING,
                                                               AlarmSeverity.SERIOUS,
                                                               AlarmSeverity.SERIOUS])

        asyncio.new_event_loop().run_until_complete(doit())


if __name__ == "__main__":
    unittest.main()
