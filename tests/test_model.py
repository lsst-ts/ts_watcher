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
import contextlib
import types
import unittest

from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts import salobj
from lsst.ts import watcher


class GetRuleClassTestCase(unittest.TestCase):
    """Test `lsst.ts.watcher.get_rule_class`."""

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


class ModelTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()

    @contextlib.asynccontextmanager
    async def make_model(self, names, enable, escalation=()):
        """Make a Model as self.model, with one or more Enabled rules.

        Parameters
        ----------
        names : `list` [`str`]
            Name and index of one or more CSCs.
            Each entry is of the form "name" or name:index".
            The associated alarm names have a prefix of "Enabled.".
        enable : `bool`
            Enable the model?
        escalation : `list` of `dict`, optional
            Escalation information.
            See `CONFIG_SCHEMA` for the format of entries.
        """
        if not names:
            raise ValueError("Must specify one or more CSCs")
        self.name_index_list = [salobj.name_to_name_index(name) for name in names]

        configs = [dict(name=name_index) for name_index in names]
        watcher_config_dict = dict(
            disabled_sal_components=[],
            auto_acknowledge_delay=3600,
            auto_unacknowledge_delay=3600,
            rules=[dict(classname="Enabled", configs=configs)],
            escalation=escalation,
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)

        self.read_severities = dict()
        self.read_max_severities = dict()

        self.controllers = []
        for name_index in names:
            name, index = salobj.name_to_name_index(name_index)
            self.controllers.append(salobj.Controller(name=name, index=index))
        self.model = watcher.Model(
            domain=self.controllers[0].domain,
            config=watcher_config,
            alarm_callback=self.alarm_callback,
        )

        for name in self.model.rules:
            self.read_severities[name] = []
            self.read_max_severities[name] = []

        controller_start_tasks = [
            controller.start_task for controller in self.controllers
        ]
        await asyncio.gather(self.model.start_task, *controller_start_tasks)
        if enable:
            self.model.enable()
            await self.model.enable_task

        for rule in self.model.rules.values():
            self.assertTrue(rule.alarm.nominal)
            self.assertFalse(rule.alarm.acknowledged)
            self.assertFalse(rule.alarm.muted)
            self.assertNotMuted(rule.alarm)

        try:
            yield
        finally:
            await self.model.close()
            controller_close_tasks = [
                asyncio.create_task(controller.close())
                for controller in self.controllers
            ]
            await asyncio.gather(*controller_close_tasks)

    def alarm_callback(self, alarm):
        """Callback function for each alarm.

        Updates self.read_severities and self.read_max_severities,
        dicts of alarm_name: list of severity/max_severity.
        """
        self.read_severities[alarm.name].append(alarm.severity)
        self.read_max_severities[alarm.name].append(alarm.max_severity)
        # Print the state to aid debugging test failures.
        print(
            f"alarm_callback({alarm.name}, severity={alarm.severity!r}): "
            f"read_severities={self.read_severities[alarm.name]}"
        )

    async def write_states(self, index, states):
        """Write a sequence of summary states to a specified controller."""
        controller = self.controllers[index]
        for state in states:
            controller.evt_summaryState.set_put(summaryState=state, force_output=True)
            # give the remote a chance to read the data
            await asyncio.sleep(0.01)

    def assert_muted(self, alarm, muted_severity, muted_by):
        """Assert that the specified alarm is muted.

        Parameters
        ----------
        alarm : `lsst.ts.watcher.Alarm`
            Alarm to test.
        muted_severity : `lsst.ts.idl.enums.Watcher.AlarmSeverity`
            Expected value for rule.severity.
        muted_by : `str`
            Expected value for rule.muted_by.
        """
        self.assertTrue(alarm.muted)
        self.assertEqual(alarm.muted_severity, muted_severity)
        self.assertEqual(alarm.muted_by, muted_by)

    def assertNotMuted(self, alarm):
        """Assert that the specified alarm is not muted.

        Parameters
        ----------
        alarm : `lsst.ts.watcher.Alarm`
            Alarm to test.
        """
        self.assertFalse(alarm.muted)
        self.assertEqual(alarm.muted_severity, AlarmSeverity.NONE)
        self.assertEqual(alarm.muted_by, "")

    async def test_acknowledge_full_name(self):
        user = "test_ack_alarm"
        remote_names = ["ScriptQueue:5", "Test:7"]
        nrules = len(remote_names)

        async with self.make_model(names=remote_names, enable=True):
            full_rule_name = f"Enabled.{remote_names[0]}"
            self.assertIn(full_rule_name, self.model.rules)

            # Send STANDBY to all controllers to put all alarms into warning.
            for index in range(nrules):
                await self.write_states(index=index, states=[salobj.State.STANDBY])

            for name, rule in self.model.rules.items():
                self.assertFalse(rule.alarm.nominal)
                self.assertEqual(rule.alarm.severity, AlarmSeverity.WARNING)
                self.assertEqual(rule.alarm.max_severity, AlarmSeverity.WARNING)

            # Acknowledge one rule by full name but not the other.
            self.model.acknowledge_alarm(
                name=full_rule_name, severity=AlarmSeverity.WARNING, user=user
            )
            for name, rule in self.model.rules.items():
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

        async with self.make_model(names=remote_names, enable=True):
            self.assertEqual(len(self.model.rules), nrules)

            # Send STANDBY to all controllers to put all alarms into warning.
            for index in range(nrules):
                await self.write_states(index=index, states=[salobj.State.STANDBY])

            for rule in self.model.rules.values():
                self.assertFalse(rule.alarm.nominal)
                self.assertEqual(rule.alarm.severity, AlarmSeverity.WARNING)
                self.assertEqual(rule.alarm.max_severity, AlarmSeverity.WARNING)

            # Acknowledge the ScriptQueue alarms but not Test.
            self.model.acknowledge_alarm(
                name="Enabled.ScriptQueue:*", severity=AlarmSeverity.WARNING, user=user
            )
            for name, rule in self.model.rules.items():
                if "ScriptQueue" in name:
                    self.assertTrue(rule.alarm.acknowledged)
                    self.assertEqual(rule.alarm.acknowledged_by, user)
                else:
                    self.assertFalse(rule.alarm.acknowledged)
                    self.assertEqual(rule.alarm.acknowledged_by, "")

    async def test_enable(self):
        remote_names = ["ScriptQueue:5", "Test:7"]

        async with self.make_model(names=remote_names, enable=True):

            self.assertEqual(len(self.model.rules), 2)

            # Enable the model and write ENABLED several times.
            # This triggers the rule callback but that does not
            # change the state of the alarm.
            self.model.enable()
            await self.model.enable_task
            for index in range(len(remote_names)):
                await self.write_states(
                    index=index,
                    states=(
                        salobj.State.ENABLED,
                        salobj.State.ENABLED,
                        salobj.State.ENABLED,
                    ),
                )

            for name, rule in self.model.rules.items():
                self.assertTrue(rule.alarm.nominal)
                self.assertEqual(self.read_severities[name], [])
                self.assertEqual(self.read_max_severities[name], [])

            # Disable the model and issue several events that would
            # trigger an alarm if the model was enabled. Since the
            # model is disabled the alarm does not change states.
            self.model.disable()
            for index in range(len(remote_names)):
                await self.write_states(
                    index=index, states=(salobj.State.FAULT, salobj.State.STANDBY)
                )
            for name, rule in self.model.rules.items():
                self.assertTrue(rule.alarm.nominal)
                self.assertEqual(self.read_severities[name], [])
                self.assertEqual(self.read_max_severities[name], [])

            # Enable the model. This will trigger a callback with
            # the current state of the event (STANDBY).
            # Note that the earlier FAULT event is is ignored
            # because it arrived while disabled.
            self.model.enable()
            await self.model.enable_task
            for name, rule in self.model.rules.items():
                self.assertFalse(rule.alarm.nominal)
                self.assertEqual(rule.alarm.severity, AlarmSeverity.WARNING)
                self.assertEqual(rule.alarm.max_severity, AlarmSeverity.WARNING)
                self.assertEqual(self.read_severities[name], [AlarmSeverity.WARNING])
                self.assertEqual(
                    self.read_max_severities[name], [AlarmSeverity.WARNING]
                )

            # Issue more events; they should be processed normally.
            for index in range(len(remote_names)):
                await self.write_states(
                    index=index, states=(salobj.State.FAULT, salobj.State.STANDBY)
                )
            for name, rule in self.model.rules.items():
                self.assertFalse(rule.alarm.nominal)
                self.assertEqual(rule.alarm.severity, AlarmSeverity.WARNING)
                self.assertEqual(rule.alarm.max_severity, AlarmSeverity.SERIOUS)
                self.assertEqual(
                    self.read_severities[name],
                    [
                        AlarmSeverity.WARNING,
                        AlarmSeverity.SERIOUS,
                        AlarmSeverity.WARNING,
                    ],
                )
                self.assertEqual(
                    self.read_max_severities[name],
                    [
                        AlarmSeverity.WARNING,
                        AlarmSeverity.SERIOUS,
                        AlarmSeverity.SERIOUS,
                    ],
                )

    async def test_escalation(self):
        remote_names = ["ScriptQueue:1", "ScriptQueue:2", "Test:1", "Test:2", "Test:52"]
        # Escalation info for the first two rules;
        # check that case does not have to match.
        esc_info12 = dict(alarms=["enabled.scriptqueue:*"], to="chaos", delay=0.11)
        # Escalation info for the next two rules
        esc_info34 = dict(alarms=["Enabled.Test:?"], to="stella", delay=0.12)
        # Escalation info that does not match any alarm names
        esc_notused = dict(alarms=["Enabled.NoMatch"], to="otho", delay=0.13)

        async with self.make_model(
            names=remote_names,
            enable=False,
            escalation=[esc_info12, esc_info34, esc_notused],
        ):
            alarms = [rule.alarm for rule in self.model.rules.values()]
            self.assertEqual(len(alarms), len(remote_names))
            for alarm in alarms[0:2]:
                self.assertEqual(alarm.escalate_to, esc_info12["to"])
                self.assertEqual(alarm.escalate_delay, esc_info12["delay"])
            for alarm in alarms[2:4]:
                self.assertEqual(alarm.escalate_to, esc_info34["to"])
                self.assertEqual(alarm.escalate_delay, esc_info34["delay"])
            for alarm in alarms[4:]:
                self.assertEqual(alarm.escalate_to, "")
                self.assertEqual(alarm.escalate_delay, 0)
            for alarm in alarms:
                self.assertEqual(alarm.timestamp_escalate, 0)

    async def test_get_rules(self):
        remote_names = ["ScriptQueue:1", "ScriptQueue:2", "Test:1", "Test:2", "Test:52"]

        async with self.make_model(names=remote_names, enable=False):
            rules = self.model.get_rules("NoSuchName")
            self.assertEqual(len(list(rules)), 0)

            # Search starts at beginning, so Enabled.foo works
            # but foo does not.
            rules = self.model.get_rules("ScriptQueue")
            self.assertEqual(len(list(rules)), 0)

            rules = self.model.get_rules(".*")
            self.assertEqual(len(list(rules)), len(remote_names))

            rules = self.model.get_rules("Enabled")
            self.assertEqual(len(list(rules)), len(remote_names))

            rules = self.model.get_rules("Enabled.ScriptQueue")
            self.assertEqual(len(list(rules)), 2)

            rules = self.model.get_rules("Enabled.Test")
            self.assertEqual(len(list(rules)), 3)

    async def test_mute_full_name(self):
        """Test mute and unmute by full alarm name."""
        user = "test_mute_alarm"
        remote_names = ["ScriptQueue:5", "Test:7"]

        async with self.make_model(names=remote_names, enable=True):
            full_rule_name = f"Enabled.{remote_names[0]}"
            self.assertIn(full_rule_name, self.model.rules)

            # Mute one rule by full name.
            self.model.mute_alarm(
                name=full_rule_name,
                duration=5,
                severity=AlarmSeverity.WARNING,
                user=user,
            )
            for name, rule in self.model.rules.items():
                if name == full_rule_name:
                    self.assert_muted(
                        rule.alarm, muted_severity=AlarmSeverity.WARNING, muted_by=user
                    )
                else:
                    self.assertNotMuted(rule.alarm)

            # Nnmute one rule by full name.
            self.model.unmute_alarm(name=full_rule_name)
            for rule in self.model.rules.values():
                self.assertNotMuted(rule.alarm)

    async def test_mute_regex(self):
        """Test mute and unmute by regex."""
        user = "test_mute_alarm"
        remote_names = ["ScriptQueue:1", "ScriptQueue:2", "Test:62"]
        nrules = len(remote_names)

        async with self.make_model(names=remote_names, enable=True):
            self.assertEqual(len(self.model.rules), nrules)

            # Mute the ScriptQueue alarms but not Test.
            self.model.mute_alarm(
                name="Enabled.ScriptQueue.*",
                duration=5,
                severity=AlarmSeverity.WARNING,
                user=user,
            )
            for name, rule in self.model.rules.items():
                if "ScriptQueue" in name:
                    self.assert_muted(
                        rule.alarm, muted_severity=AlarmSeverity.WARNING, muted_by=user
                    )
                else:
                    self.assertNotMuted(rule.alarm)

            # Unmute the ScriptQueue alarms but not Test.
            self.model.unmute_alarm(name="Enabled.ScriptQueue.*")
            for rule in self.model.rules.values():
                self.assertNotMuted(rule.alarm)


if __name__ == "__main__":
    unittest.main()
