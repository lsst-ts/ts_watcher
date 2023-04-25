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

import pytest
from lsst.ts import salobj, watcher
from lsst.ts.idl.enums.Watcher import AlarmSeverity

# Timeout for normal operations (seconds)
STD_TIMEOUT = 5


class GetRuleClassTestCase(unittest.TestCase):
    """Test `lsst.ts.watcher.get_rule_class`."""

    def test_good_names(self):
        for classname, desired_class in (
            ("Enabled", watcher.rules.Enabled),
            ("test.NoConfig", watcher.rules.test.NoConfig),
            ("test.ConfiguredSeverities", watcher.rules.test.ConfiguredSeverities),
        ):
            rule_class = watcher.get_rule_class(classname)
            assert rule_class == desired_class

    def test_bad_names(self):
        for bad_name in (
            "NoSuchRule",  # no such rule
            "test.NoSuchRule",  # no such rule
            "test.Enabled",  # wrong module
            "NoConfig",  # wrong module
            "test_NoConfig",  # wrong separator
        ):
            with pytest.raises(ValueError):
                watcher.get_rule_class(bad_name)


class ModelTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()

    @contextlib.asynccontextmanager
    async def make_model(self, names, enable, escalation=(), use_bad_callback=False):
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
        use_bad_callback : `bool`
            If True then specify an invalid callback function:
            one that is synchronous. This should raise TypeError.
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

        if use_bad_callback:

            def bad_callback():
                pass

            alarm_callback = bad_callback
        else:
            alarm_callback = self.alarm_callback

        self.model = watcher.Model(
            domain=self.controllers[0].domain,
            config=watcher_config,
            alarm_callback=alarm_callback,
        )

        for name, rule in self.model.rules.items():
            rule.alarm.init_severity_queue()
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
            assert rule.alarm.nominal
            assert not rule.alarm.acknowledged
            assert not rule.alarm.muted
            self.assert_not_muted(rule.alarm)

        try:
            yield
        finally:
            await self.model.close()
            controller_close_tasks = [
                asyncio.create_task(controller.close())
                for controller in self.controllers
            ]
            await asyncio.gather(*controller_close_tasks)

    async def alarm_callback(self, alarm):
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
        controller_name_index = f"{controller.salinfo.name}:{controller.salinfo.index}"
        rule_name = f"Enabled.{controller_name_index}"
        rule = self.model.rules[rule_name]
        for state in states:
            await controller.evt_summaryState.set_write(
                summaryState=state, force_output=True
            )
            if self.model.enabled:
                await asyncio.wait_for(
                    rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT
                )
                assert rule.alarm.severity_queue.empty()
            else:
                # We don't have any event we can wait for, so sleep a bit
                # to give the model time to react to the data.
                await asyncio.sleep(0.1)

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
        assert alarm.muted
        assert alarm.muted_severity == muted_severity
        assert alarm.muted_by == muted_by

    def assert_not_muted(self, alarm):
        """Assert that the specified alarm is not muted.

        Parameters
        ----------
        alarm : `lsst.ts.watcher.Alarm`
            Alarm to test.
        """
        assert not alarm.muted
        assert alarm.muted_severity == AlarmSeverity.NONE
        assert alarm.muted_by == ""

    async def test_constructor_bad_callback(self):
        remote_names = ["ScriptQueue:5", "Test:7"]
        with pytest.raises(TypeError):
            async with self.make_model(
                names=remote_names, enable=False, use_bad_callback=True
            ):
                pass

    async def test_acknowledge_full_name(self):
        user = "test_ack_alarm"
        remote_names = ["ScriptQueue:5", "Test:7"]
        nrules = len(remote_names)

        async with self.make_model(names=remote_names, enable=True):
            full_rule_name = f"Enabled.{remote_names[0]}"
            assert full_rule_name in self.model.rules

            # Send STANDBY to all controllers to put all alarms into warning.
            for index in range(nrules):
                await self.write_states(index=index, states=[salobj.State.STANDBY])

            for name, rule in self.model.rules.items():
                assert not rule.alarm.nominal
                assert rule.alarm.severity == AlarmSeverity.WARNING
                assert rule.alarm.max_severity == AlarmSeverity.WARNING

            # Acknowledge one rule by full name but not the other.
            await self.model.acknowledge_alarm(
                name=full_rule_name, severity=AlarmSeverity.WARNING, user=user
            )
            for name, rule in self.model.rules.items():
                if name == full_rule_name:
                    assert rule.alarm.acknowledged
                    assert rule.alarm.acknowledged_by == user
                else:
                    assert not rule.alarm.acknowledged
                    assert rule.alarm.acknowledged_by == ""

    async def test_acknowledge_regex(self):
        user = "test_ack_alarm"
        remote_names = ["ScriptQueue:1", "ScriptQueue:2", "Test:62"]
        nrules = len(remote_names)

        async with self.make_model(names=remote_names, enable=True):
            assert len(self.model.rules) == nrules

            # Send STANDBY to all controllers to put all alarms into warning.
            for index in range(nrules):
                await self.write_states(index=index, states=[salobj.State.STANDBY])

            for rule in self.model.rules.values():
                assert not rule.alarm.nominal
                assert rule.alarm.severity == AlarmSeverity.WARNING
                assert rule.alarm.max_severity == AlarmSeverity.WARNING

            # Acknowledge the ScriptQueue alarms but not Test.
            await self.model.acknowledge_alarm(
                name="Enabled.ScriptQueue:*", severity=AlarmSeverity.WARNING, user=user
            )
            for name, rule in self.model.rules.items():
                if "ScriptQueue" in name:
                    assert rule.alarm.acknowledged
                    assert rule.alarm.acknowledged_by == user
                else:
                    assert not rule.alarm.acknowledged
                    assert rule.alarm.acknowledged_by == ""

    async def test_enable(self):
        remote_names = ["ScriptQueue:5", "Test:7"]

        async with self.make_model(names=remote_names, enable=True):
            assert len(self.model.rules) == 2

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
                assert rule.alarm.nominal
                assert self.read_severities[name] == []
                assert self.read_max_severities[name] == []

            # Disable the model and issue several events that would
            # trigger an alarm if the model was enabled. Since the
            # model is disabled the alarm does not change states.
            self.model.disable()
            for index in range(len(remote_names)):
                await self.write_states(
                    index=index, states=(salobj.State.FAULT, salobj.State.STANDBY)
                )

            for name, rule in self.model.rules.items():
                assert rule.alarm.nominal
                assert self.read_severities[name] == []
                assert self.read_max_severities[name] == []

            # Enable the model. This will trigger a callback with
            # the current state of the event (STANDBY).
            # Note that the earlier FAULT event is is ignored
            # because it arrived while disabled.
            self.model.enable()
            await self.model.enable_task
            for name, rule in self.model.rules.items():
                await rule.alarm.assert_next_severity(AlarmSeverity.WARNING)
                assert not rule.alarm.nominal
                assert rule.alarm.severity == AlarmSeverity.WARNING
                assert rule.alarm.max_severity == AlarmSeverity.WARNING
                assert self.read_severities[name] == [AlarmSeverity.WARNING]
                assert self.read_max_severities[name] == [AlarmSeverity.WARNING]

            # Issue more events; they should be processed normally.
            for index in range(len(remote_names)):
                await self.write_states(
                    index=index, states=(salobj.State.FAULT, salobj.State.STANDBY)
                )

            for name, rule in self.model.rules.items():
                assert not rule.alarm.nominal
                assert rule.alarm.severity == AlarmSeverity.WARNING
                assert rule.alarm.max_severity == AlarmSeverity.CRITICAL
                assert self.read_severities[name] == [
                    AlarmSeverity.WARNING,
                    AlarmSeverity.CRITICAL,
                    AlarmSeverity.WARNING,
                ]
                assert self.read_max_severities[name] == [
                    AlarmSeverity.WARNING,
                    AlarmSeverity.CRITICAL,
                    AlarmSeverity.CRITICAL,
                ]

    async def test_escalation(self):
        remote_names = ["ScriptQueue:1", "ScriptQueue:2", "Test:1", "Test:2", "Test:52"]
        # Escalation info for the first two rules;
        # check that case does not have to match.
        esc_info12 = dict(
            alarms=["enabled.scriptqueue:*"],
            responder="chaos",
            delay=0.11,
        )
        # Escalation info for the next two rules
        esc_info34 = dict(
            alarms=["Enabled.Test:?"],
            responder="stella",
            delay=0.12,
        )
        # Escalation info that does not match any alarm names
        esc_notused = dict(
            alarms=["Enabled.NoMatch"],
            responder="someone",
            delay=0.13,
        )

        async with self.make_model(
            names=remote_names,
            enable=False,
            escalation=[esc_info12, esc_info34, esc_notused],
        ):
            alarms = [rule.alarm for rule in self.model.rules.values()]
            assert len(alarms) == len(remote_names)
            for alarm in alarms[0:2]:
                assert alarm.escalation_responder == esc_info12["responder"]
                assert alarm.escalation_delay == esc_info12["delay"]
            for alarm in alarms[2:4]:
                assert alarm.escalation_responder == esc_info34["responder"]
                assert alarm.escalation_delay == esc_info34["delay"]
            for alarm in alarms[4:]:
                assert alarm.escalation_responder == ""
                assert alarm.escalation_delay == 0
            for alarm in alarms:
                assert alarm.timestamp_escalate == 0

    async def test_get_rules(self):
        remote_names = ["ScriptQueue:1", "ScriptQueue:2", "Test:1", "Test:2", "Test:52"]

        async with self.make_model(names=remote_names, enable=False):
            rules = self.model.get_rules("NoSuchName")
            assert len(list(rules)) == 0

            # Search starts at beginning, so Enabled.foo works
            # but foo does not.
            rules = self.model.get_rules("ScriptQueue")
            assert len(list(rules)) == 0

            rules = self.model.get_rules(".*")
            assert len(list(rules)) == len(remote_names)

            rules = self.model.get_rules("Enabled")
            assert len(list(rules)) == len(remote_names)

            rules = self.model.get_rules("Enabled.ScriptQueue")
            assert len(list(rules)) == 2

            rules = self.model.get_rules("Enabled.Test")
            assert len(list(rules)) == 3

    async def test_mute_full_name(self):
        """Test mute and unmute by full alarm name."""
        user = "test_mute_alarm"
        remote_names = ["ScriptQueue:5", "Test:7"]

        async with self.make_model(names=remote_names, enable=True):
            full_rule_name = f"Enabled.{remote_names[0]}"
            assert full_rule_name in self.model.rules

            # Mute one rule by full name.
            await self.model.mute_alarm(
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
                    self.assert_not_muted(rule.alarm)

            # Nnmute one rule by full name.
            await self.model.unmute_alarm(name=full_rule_name)
            for rule in self.model.rules.values():
                self.assert_not_muted(rule.alarm)

    async def test_mute_regex(self):
        """Test mute and unmute by regex."""
        user = "test_mute_alarm"
        remote_names = ["ScriptQueue:1", "ScriptQueue:2", "Test:62"]
        nrules = len(remote_names)

        async with self.make_model(names=remote_names, enable=True):
            assert len(self.model.rules) == nrules

            # Mute the ScriptQueue alarms but not Test.
            await self.model.mute_alarm(
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
                    self.assert_not_muted(rule.alarm)

            # Unmute the ScriptQueue alarms but not Test.
            await self.model.unmute_alarm(name="Enabled.ScriptQueue.*")
            for rule in self.model.rules.values():
                self.assert_not_muted(rule.alarm)
