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


class GetRuleClassTestCase(unittest.TestCase):
    """Test Watcher.get_rule_class.
    """
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


class EnabledRulesHarness:
    """Make a Model with one or more Enabled rules.

    Parameters
    ----------
    names : `list`[ `str` ]
        Name and index of one or more CSCs.
        Each entry is of the form "name" or name:index"
    """
    def __init__(self, names=("ScriptQueue:5",)):
        if not names:
            raise ValueError("Must specify one or more CSCs")
        self.name_index_list = [salobj.name_to_name_index(name) for name in names]

        configs = [dict(name=name_index) for name_index in names]
        watcher_config_dict = dict(disabled_sal_components=[],
                                   rules=[dict(classname="Enabled",
                                               configs=configs)])
        watcher_config = types.SimpleNamespace(**watcher_config_dict)

        self.read_severities = dict()
        self.read_max_severities = dict()

        self.controllers = []
        for name_index in names:
            name, index = salobj.name_to_name_index(name_index)
            self.controllers.append(salobj.Controller(name=name, index=index))
        self.model = watcher.Model(domain=self.controllers[0].domain,
                                   config=watcher_config,
                                   alarm_callback=self.alarm_callback)

        for name in self.model.rules:
            self.read_severities[name] = []
            self.read_max_severities[name] = []

    def alarm_callback(self, alarm):
        self.read_severities[alarm.name].append(alarm.severity)
        self.read_max_severities[alarm.name].append(alarm.max_severity)
        print(f"alarm_callback({alarm.name}, severity={alarm.severity!r}): "
              f"read_severities={self.read_severities[alarm.name]}")

    async def write_states(self, index, states):
        """Write a sequence of summary states to a specified controller.
        """
        controller = self.controllers[index]
        for state in states:
            controller.evt_summaryState.set_put(summaryState=state, force_output=True)
            # give the remote a chance to read the data
            await asyncio.sleep(0.01)

    async def __aenter__(self):
        controller_start_tasks = [controller.start_task for controller in self.controllers]
        await asyncio.gather(self.model.start_task, *controller_start_tasks)
        return self

    async def __aexit__(self, *args):
        await self.model.close()
        controller_close_tasks = [asyncio.create_task(controller.close()) for controller in self.controllers]
        await asyncio.gather(*controller_close_tasks)


class ModelTestCase(asynctest.TestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_domain()

    async def test_acknowledge_full_name(self):
        user = "test_ack_alarm"
        remote_names = ["ScriptQueue:5", "Test:7"]
        nrules = len(remote_names)

        async with EnabledRulesHarness(names=remote_names) as harness:

            harness.model.enable()
            await harness.model.enable_task

            full_rule_name = f"Enabled.{remote_names[0]}"
            self.assertIn(full_rule_name, harness.model.rules)

            for rule in harness.model.rules.values():
                self.assertTrue(rule.alarm.nominal)
                self.assertFalse(rule.alarm.acknowledged)

            # send STANDBY to all controllers to put all alarms into warning
            for index in range(nrules):
                await harness.write_states(index=index, states=[salobj.State.STANDBY])

            for name, rule in harness.model.rules.items():
                self.assertFalse(rule.alarm.nominal)
                self.assertEqual(rule.alarm.severity, AlarmSeverity.WARNING)
                self.assertEqual(rule.alarm.max_severity, AlarmSeverity.WARNING)

            # acknowledge one rule by full name but not the other
            harness.model.acknowledge_alarm(name=full_rule_name,
                                            severity=AlarmSeverity.WARNING,
                                            user=user)
            for name, rule in harness.model.rules.items():
                if name == full_rule_name:
                    self.assertTrue(rule.alarm.acknowledged)
                    self.assertEqual(rule.alarm.acknowledged_by, user)
                else:
                    self.assertFalse(rule.alarm.acknowledged)
                    self.assertEqual(rule.alarm.acknowledged_by, "")

    async def test_acknowledge_regex(self):
        user = "test_ack_alarm"
        remote_names = ["ScriptQueue:1", "ScriptQueue:2", "Test:62"]
        nrules = len(remote_names)

        async with EnabledRulesHarness(names=remote_names) as harness:

            harness.model.enable()
            await harness.model.enable_task

            self.assertEqual(len(harness.model.rules), nrules)

            for rule in harness.model.rules.values():
                self.assertTrue(rule.alarm.nominal)
                self.assertFalse(rule.alarm.acknowledged)

            # send STANDBY to all controllers to put all alarms into warning
            for index in range(nrules):
                await harness.write_states(index=index, states=[salobj.State.STANDBY])

            for rule in harness.model.rules.values():
                self.assertFalse(rule.alarm.nominal)
                self.assertEqual(rule.alarm.severity, AlarmSeverity.WARNING)
                self.assertEqual(rule.alarm.max_severity, AlarmSeverity.WARNING)

            # acknowledge the ScriptQueue alarms but not Test
            harness.model.acknowledge_alarm(name="Enabled.ScriptQueue.*",
                                            severity=AlarmSeverity.WARNING,
                                            user=user)
            for name, rule in harness.model.rules.items():
                if "ScriptQueue" in name:
                    self.assertTrue(rule.alarm.acknowledged)
                    self.assertEqual(rule.alarm.acknowledged_by, user)
                else:
                    self.assertFalse(rule.alarm.acknowledged)
                    self.assertEqual(rule.alarm.acknowledged_by, "")

    async def test_enable(self):
        remote_names = ["ScriptQueue:5", "Test:7"]

        async with EnabledRulesHarness(names=remote_names) as harness:

            self.assertEqual(len(harness.model.rules), 2)

            # Enable the model and write ENABLED several times.
            # This triggers the rule callback but that does not
            # change the state of the alarm.
            harness.model.enable()
            await harness.model.enable_task
            for index in range(len(remote_names)):
                await harness.write_states(index=index, states=(salobj.State.ENABLED,
                                                                salobj.State.ENABLED,
                                                                salobj.State.ENABLED))

            for name, rule in harness.model.rules.items():
                self.assertTrue(rule.alarm.nominal)
                self.assertEqual(harness.read_severities[name], [])
                self.assertEqual(harness.read_max_severities[name], [])

            # Disable the model and issue several events that would
            # trigger an alarm if the model was enabled. Since the
            # model is disabled the alarm does not change states.
            harness.model.disable()
            for index in range(len(remote_names)):
                await harness.write_states(index=index, states=(salobj.State.FAULT,
                                                                salobj.State.STANDBY))
            for name, rule in harness.model.rules.items():
                self.assertTrue(rule.alarm.nominal)
                self.assertEqual(harness.read_severities[name], [])
                self.assertEqual(harness.read_max_severities[name], [])

            # Enable the model. This will trigger a callback with
            # the current state of the event (STANDBY).
            # Note that the earlier FAULT event is is ignored
            # because it arrived while disabled.
            harness.model.enable()
            await harness.model.enable_task
            for name, rule in harness.model.rules.items():
                self.assertFalse(rule.alarm.nominal)
                self.assertEqual(rule.alarm.severity, AlarmSeverity.WARNING)
                self.assertEqual(rule.alarm.max_severity, AlarmSeverity.WARNING)
                self.assertEqual(harness.read_severities[name], [AlarmSeverity.WARNING])
                self.assertEqual(harness.read_max_severities[name], [AlarmSeverity.WARNING])

            # Issue more events; they should be processed normally.
            for index in range(len(remote_names)):
                await harness.write_states(index=index, states=(salobj.State.FAULT,
                                                                salobj.State.STANDBY))
            for name, rule in harness.model.rules.items():
                self.assertFalse(rule.alarm.nominal)
                self.assertEqual(rule.alarm.severity, AlarmSeverity.WARNING)
                self.assertEqual(rule.alarm.max_severity, AlarmSeverity.SERIOUS)
                self.assertEqual(harness.read_severities[name], [AlarmSeverity.WARNING,
                                                                 AlarmSeverity.SERIOUS,
                                                                 AlarmSeverity.WARNING])
                self.assertEqual(harness.read_max_severities[name], [AlarmSeverity.WARNING,
                                                                     AlarmSeverity.SERIOUS,
                                                                     AlarmSeverity.SERIOUS])

    async def test_get_rules(self):
        remote_names = ["ScriptQueue:1", "ScriptQueue:2", "Test:1", "Test:2", "Test:52"]

        async with EnabledRulesHarness(names=remote_names) as harness:
            rules = harness.model.get_rules("NoSuchName")
            self.assertEqual(len(list(rules)), 0)

            # search starts at beginning, so Enabled.foo works
            # but foo does not
            rules = harness.model.get_rules("ScriptQueue")
            self.assertEqual(len(list(rules)), 0)

            rules = harness.model.get_rules(".*")
            self.assertEqual(len(list(rules)), len(remote_names))

            rules = harness.model.get_rules("Enabled")
            self.assertEqual(len(list(rules)), len(remote_names))

            rules = harness.model.get_rules("Enabled.ScriptQueue")
            self.assertEqual(len(list(rules)), 2)

            rules = harness.model.get_rules("Enabled.Test")
            self.assertEqual(len(list(rules)), 3)


if __name__ == "__main__":
    unittest.main()
