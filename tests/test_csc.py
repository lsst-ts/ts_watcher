# This file is part of ts_Watcher.
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

import asyncio
import glob
import os
import pathlib
import sys
import unittest

import asynctest

from lsst.ts import salobj
from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts import watcher

STD_TIMEOUT = 2  # standard command timeout (sec)
NODATA_TIMEOUT = 1  # timeout when no data is expected (sec)
LONG_TIMEOUT = 20  # timeout for starting SAL components (sec)
TEST_CONFIG_DIR = pathlib.Path(__file__).parents[1] / "tests" / "data" / "config"


class CscTestCase(salobj.BaseCscTestCase, asynctest.TestCase):
    def basic_make_csc(self, initial_state, config_dir, simulation_mode):
        self.assertEqual(initial_state, salobj.State.STANDBY)
        self.assertEqual(simulation_mode, 0)
        return watcher.WatcherCsc(config_dir=config_dir)

    async def assert_next_alarm(
        self, timeout=STD_TIMEOUT, **kwargs,
    ):
        """Wait for the next alarm event and check its fields.

        Return the alarm data, in case you want to do anything else with it
        (such as access its name).

        Parameters
        ----------
        **kwargs : `dict`
            A dict of data field name: expected value
        timeout : `float`, optional
            Time limit (sec).

        Returns
        -------
        data : Alarm data
            The read message.
        """
        data = await self.remote.evt_alarm.next(flush=False, timeout=timeout)
        for name, value in kwargs.items():
            self.assertEqual(getattr(data, name), value, msg=name)
        return data

    async def test_bin_script(self):
        await self.check_bin_script(
            name="Watcher", index=None, exe_name="run_watcher.py",
        )

    async def test_initial_info(self):
        async with self.make_csc(
            config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY
        ):
            await self.assert_next_summary_state(salobj.State.STANDBY)
            self.assertIsNone(self.csc.model)

            await salobj.set_summary_state(
                self.remote,
                salobj.State.ENABLED,
                settingsToApply="two_scriptqueue_enabled.yaml",
            )
            await self.assert_next_summary_state(salobj.State.DISABLED)
            await self.assert_next_summary_state(salobj.State.ENABLED)
            self.assertIsInstance(self.csc.model, watcher.Model)
            rule_names = list(self.csc.model.rules)
            expected_rule_names = [f"Enabled.ScriptQueue:{index}" for index in (1, 2)]
            self.assertEqual(rule_names, expected_rule_names)

            # Check that escalation info is not set for the first rule
            # and is set for the second rule.
            alarm1 = self.csc.model.rules[expected_rule_names[0]].alarm
            alarm2 = self.csc.model.rules[expected_rule_names[1]].alarm
            self.assertEqual(alarm1.escalate_to, "")
            self.assertEqual(alarm1.escalate_delay, 0)
            self.assertEqual(alarm1.timestamp_escalate, 0)
            self.assertFalse(alarm1.escalated)
            self.assertEqual(alarm2.escalate_to, "stella")
            self.assertEqual(alarm2.escalate_delay, 0.11)
            self.assertEqual(alarm2.timestamp_escalate, 0)
            self.assertFalse(alarm2.escalated)

    async def test_default_config_dir(self):
        async with self.make_csc(config_dir=None, initial_state=salobj.State.STANDBY):
            desired_config_pkg_name = "ts_config_ocs"
            desired_config_env_name = desired_config_pkg_name.upper() + "_DIR"
            desird_config_pkg_dir = os.environ[desired_config_env_name]
            desired_config_dir = pathlib.Path(desird_config_pkg_dir) / "Watcher/v1"
            self.assertEqual(self.csc.get_config_pkg(), desired_config_pkg_name)
            self.assertEqual(self.csc.config_dir, desired_config_dir)

    async def test_configuration_invalid(self):
        async with self.make_csc(
            config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY
        ):
            invalid_files = glob.glob(str(TEST_CONFIG_DIR / "invalid_*.yaml"))
            # Test the invalid files and a blank settingsToApply
            # (since the schema doesn't have a usable default).
            bad_config_names = [os.path.basename(name) for name in invalid_files] + [""]
            for bad_config_name in bad_config_names:
                with self.subTest(bad_config_name=bad_config_name):
                    with salobj.assertRaisesAckError(ack=salobj.SalRetCode.CMD_FAILED):
                        await self.remote.cmd_start.set_start(
                            settingsToApply=bad_config_name, timeout=STD_TIMEOUT
                        )

            # Check that the CSC can still be configured.
            # This also exercises specifying a rule with no configuration.
            await self.remote.cmd_start.set_start(
                settingsToApply="basic.yaml", timeout=STD_TIMEOUT
            )

    async def test_standard_state_transitions(self):
        async with self.make_csc(
            config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY
        ):
            await self.check_standard_state_transitions(
                enabled_commands=(
                    "acknowledge",
                    "mute",
                    "showAlarms",
                    "unacknowledge",
                    "unmute",
                ),
                settingsToApply="two_scriptqueue_enabled.yaml",
            )

    async def test_escalation(self):
        """Run the watcher with a ConfiguredSeverity rule and make sure
        the escalation fields look correct in the Alarm event.
        """
        async with self.make_csc(
            config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY
        ):
            await salobj.set_summary_state(
                self.remote, state=salobj.State.ENABLED, settingsToApply="critical.yaml"
            )
            alarm_name1 = "test.ConfiguredSeverities.ATDome"
            alarm_name2 = "test.ConfiguredSeverities.ATCamera"
            await self.assert_next_alarm(
                name=alarm_name1,
                severity=AlarmSeverity.WARNING,
                maxSeverity=AlarmSeverity.WARNING,
                escalated=False,
                escalateTo="stella",
                timestampEscalate=0,
            )
            await self.assert_next_alarm(
                name=alarm_name2,
                severity=AlarmSeverity.SERIOUS,
                maxSeverity=AlarmSeverity.SERIOUS,
                escalated=False,
                escalateTo="",
                timestampEscalate=0,
            )
            data = await self.assert_next_alarm(
                name=alarm_name1,
                severity=AlarmSeverity.CRITICAL,
                maxSeverity=AlarmSeverity.CRITICAL,
                escalated=False,
                escalateTo="stella",
            )
            self.assertGreater(data.timestampEscalate, 0)
            timestamp_escalate = data.timestampEscalate
            # The next event indicates that the alarm has been escalated.
            await self.assert_next_alarm(
                name=alarm_name1,
                severity=AlarmSeverity.CRITICAL,
                maxSeverity=AlarmSeverity.CRITICAL,
                escalated=True,
                escalateTo="stella",
                timestampEscalate=timestamp_escalate,
            )
            await self.assert_next_alarm(
                name=alarm_name2,
                severity=AlarmSeverity.CRITICAL,
                maxSeverity=AlarmSeverity.CRITICAL,
                escalated=False,
                escalateTo="",
                timestampEscalate=0,
            )
            await self.assert_next_alarm(
                name=alarm_name1,
                severity=AlarmSeverity.NONE,
                maxSeverity=AlarmSeverity.CRITICAL,
                escalated=True,
                escalateTo="stella",
                timestampEscalate=timestamp_escalate,
            )
            await self.assert_next_alarm(
                name=alarm_name2,
                severity=AlarmSeverity.WARNING,
                maxSeverity=AlarmSeverity.CRITICAL,
                escalated=False,
                escalateTo="",
                timestampEscalate=0,
            )

    async def test_operation(self):
        """Run the watcher with a few rules and one disabled SAL component."""
        async with self.make_csc(
            config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY
        ):
            await salobj.set_summary_state(
                self.remote, state=salobj.State.ENABLED, settingsToApply="enabled.yaml"
            )

            atdome_alarm_name = "Enabled.ATDome:0"
            scriptqueue_alarm_name = "Enabled.ScriptQueue:2"

            # Check that disabled_sal_components eliminated a rule.
            self.assertEqual(len(self.csc.model.rules), 2)
            self.assertEqual(
                list(self.csc.model.rules), [atdome_alarm_name, scriptqueue_alarm_name]
            )

            # Make summary state writers for CSCs in `enabled.yaml`.
            atdome_salinfo = salobj.SalInfo(
                domain=self.csc.domain, name="ATDome", index=0
            )
            atdome_state = salobj.topics.ControllerEvent(
                salinfo=atdome_salinfo, name="summaryState"
            )

            atdome_state.set_put(summaryState=salobj.State.DISABLED, force_output=True)
            await self.assert_next_alarm(
                name=atdome_alarm_name,
                severity=AlarmSeverity.WARNING,
                maxSeverity=AlarmSeverity.WARNING,
                acknowledged=False,
                acknowledgedBy="",
            )

            atdome_state.set_put(summaryState=salobj.State.FAULT, force_output=True)
            await self.assert_next_alarm(
                name=atdome_alarm_name,
                severity=AlarmSeverity.SERIOUS,
                maxSeverity=AlarmSeverity.SERIOUS,
                acknowledged=False,
                acknowledgedBy="",
            )

            user = "test_operation"
            await self.remote.cmd_acknowledge.set_start(
                name=atdome_alarm_name,
                severity=AlarmSeverity.SERIOUS,
                acknowledgedBy=user,
            )
            await self.assert_next_alarm(
                name=atdome_alarm_name,
                severity=AlarmSeverity.SERIOUS,
                maxSeverity=AlarmSeverity.SERIOUS,
                acknowledged=True,
                acknowledgedBy=user,
            )

            # Set the state to ENABLED; this should reset the alarm.
            atdome_state.set_put(summaryState=salobj.State.ENABLED, force_output=True)
            await self.assert_next_alarm(
                name=atdome_alarm_name,
                severity=AlarmSeverity.NONE,
                maxSeverity=AlarmSeverity.NONE,
                acknowledged=False,
                acknowledgedBy="",
            )

    async def test_auto_acknowledge_unacknowledge(self):
        user = "chaos"
        async with self.make_csc(
            config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY
        ):
            await salobj.set_summary_state(
                self.remote,
                state=salobj.State.ENABLED,
                settingsToApply="enabled_short_auto_delays.yaml",
            )

            # Check the values encoded in the yaml config file.
            expected_auto_acknowledge_delay = 0.51
            expected_auto_unacknowledge_delay = 0.52
            self.assertAlmostEqual(
                self.csc.model.config.auto_acknowledge_delay,
                expected_auto_acknowledge_delay,
            )
            self.assertAlmostEqual(
                self.csc.model.config.auto_unacknowledge_delay,
                expected_auto_unacknowledge_delay,
            )

            atdome_alarm_name = "Enabled.ATDome:0"

            # Make a summary state writer for ATDome
            atdome_salinfo = salobj.SalInfo(
                domain=self.csc.domain, name="ATDome", index=0
            )
            atdome_state = salobj.topics.ControllerEvent(
                salinfo=atdome_salinfo, name="summaryState"
            )

            # Make the ATDome alarm stale.
            atdome_state.set_put(summaryState=salobj.State.DISABLED, force_output=True)
            await self.assert_next_alarm(
                name=atdome_alarm_name,
                severity=AlarmSeverity.WARNING,
                maxSeverity=AlarmSeverity.WARNING,
                acknowledged=False,
                acknowledgedBy="",
            )

            atdome_state.set_put(summaryState=salobj.State.ENABLED, force_output=True)
            await self.assert_next_alarm(
                name=atdome_alarm_name,
                severity=AlarmSeverity.NONE,
                maxSeverity=AlarmSeverity.WARNING,
                acknowledged=False,
                acknowledgedBy="",
            )

            # Wait for automatic acknowledgement.
            t0 = salobj.current_tai()
            alarm = await self.assert_next_alarm(
                name=atdome_alarm_name,
                severity=AlarmSeverity.NONE,
                maxSeverity=AlarmSeverity.NONE,
                acknowledged=True,
                acknowledgedBy="automatic",
            )
            dt0 = salobj.current_tai() - t0
            self.assertGreaterEqual(alarm.timestampAcknowledged, t0)
            self.assertGreaterEqual(dt0, expected_auto_acknowledge_delay)

            # Make the ATDome alarm acknowledged and not stale
            atdome_state.set_put(summaryState=salobj.State.DISABLED, force_output=True)
            await self.assert_next_alarm(
                name=atdome_alarm_name,
                severity=AlarmSeverity.WARNING,
                maxSeverity=AlarmSeverity.WARNING,
                acknowledged=False,
                acknowledgedBy="",
            )

            await self.remote.cmd_acknowledge.set_start(
                name=atdome_alarm_name,
                severity=AlarmSeverity.WARNING,
                acknowledgedBy=user,
            )
            await self.assert_next_alarm(
                name=atdome_alarm_name,
                severity=AlarmSeverity.WARNING,
                maxSeverity=AlarmSeverity.WARNING,
                acknowledged=True,
                acknowledgedBy=user,
            )

            # Wait for automatic unacknowledgement
            t1 = salobj.current_tai()
            alarm = await self.assert_next_alarm(
                name=atdome_alarm_name,
                severity=AlarmSeverity.WARNING,
                maxSeverity=AlarmSeverity.WARNING,
                acknowledged=False,
                acknowledgedBy="",
            )
            dt1 = salobj.current_tai() - t1
            self.assertGreaterEqual(alarm.timestampAcknowledged, t1)
            self.assertGreaterEqual(dt1, expected_auto_unacknowledge_delay)

    async def test_show_alarms(self):
        """Test the showAlarms command."""
        async with self.make_csc(
            config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY
        ):
            await salobj.set_summary_state(
                self.remote, state=salobj.State.ENABLED, settingsToApply="enabled.yaml"
            )

            atdome_alarm_name = "Enabled.ATDome:0"
            scriptqueue_alarm_name = "Enabled.ScriptQueue:2"

            # All alarms should be nominal, so showAlarms should output
            # no alarm events.
            for rule in self.csc.model.rules.values():
                self.assertTrue(rule.alarm.nominal)
            await self.remote.cmd_showAlarms.start(timeout=STD_TIMEOUT)
            with self.assertRaises(asyncio.TimeoutError):
                await self.remote.evt_alarm.next(flush=False, timeout=NODATA_TIMEOUT)

            # Make summary state writers for CSCs in `enabled.yaml`.
            atdome_salinfo = salobj.SalInfo(
                domain=self.csc.domain, name="ATDome", index=0
            )
            atdome_state = salobj.topics.ControllerEvent(
                salinfo=atdome_salinfo, name="summaryState"
            )
            scriptqueue_salinfo = salobj.SalInfo(
                domain=self.csc.domain, name="ScriptQueue", index=2
            )
            scriptqueue_state = salobj.topics.ControllerEvent(
                salinfo=scriptqueue_salinfo, name="summaryState"
            )

            # Fire the ATDome alarm.
            atdome_state.set_put(summaryState=salobj.State.DISABLED, force_output=True)
            await self.assert_next_alarm(
                name=atdome_alarm_name,
                severity=AlarmSeverity.WARNING,
                maxSeverity=AlarmSeverity.WARNING,
                acknowledged=False,
                acknowledgedBy="",
            )

            # Fire the ScriptQueue:2 alarm.
            scriptqueue_state.set_put(
                summaryState=salobj.State.DISABLED, force_output=True
            )
            await self.assert_next_alarm(
                name=scriptqueue_alarm_name,
                severity=AlarmSeverity.WARNING,
                maxSeverity=AlarmSeverity.WARNING,
                acknowledged=False,
                acknowledgedBy="",
            )

            # We expect no more alarm events (yet).
            with self.assertRaises(asyncio.TimeoutError):
                await self.remote.evt_alarm.next(flush=False, timeout=NODATA_TIMEOUT)

            # Send the showAlarms command. This should trigger the same
            # two alarm events that we have already seen (in either order).
            await self.remote.cmd_showAlarms.start(timeout=STD_TIMEOUT)
            alarm_names = []
            for i in range(2):
                alarm = await self.assert_next_alarm(
                    severity=AlarmSeverity.WARNING,
                    maxSeverity=AlarmSeverity.WARNING,
                    acknowledged=False,
                )
                alarm_names.append(alarm.name)
            self.assertEqual(
                set(alarm_names), set(("Enabled.ATDome:0", "Enabled.ScriptQueue:2"))
            )
            with self.assertRaises(asyncio.TimeoutError):
                await self.remote.evt_alarm.next(flush=False, timeout=NODATA_TIMEOUT)

            # Acknowledge the ATDome alarm.
            user = "test_show_alarms"
            await self.remote.cmd_acknowledge.set_start(
                name=atdome_alarm_name,
                severity=AlarmSeverity.WARNING,
                acknowledgedBy=user,
            )
            await self.assert_next_alarm(
                name=atdome_alarm_name,
                severity=AlarmSeverity.WARNING,
                maxSeverity=AlarmSeverity.WARNING,
                acknowledged=True,
                acknowledgedBy=user,
            )

            # Set ATDome state to ENABLED; this should reset the alarm.
            atdome_state.set_put(summaryState=salobj.State.ENABLED, force_output=True)
            await self.assert_next_alarm(
                name=atdome_alarm_name,
                severity=AlarmSeverity.NONE,
                maxSeverity=AlarmSeverity.NONE,
                acknowledged=False,
                acknowledgedBy="",
            )

            # Send the showAlarms command again. This should trigger
            # just one alarm: Enabled.ScriptQueue:2.
            await self.remote.cmd_showAlarms.start(timeout=STD_TIMEOUT)
            await self.assert_next_alarm(
                name=scriptqueue_alarm_name,
                severity=AlarmSeverity.WARNING,
                maxSeverity=AlarmSeverity.WARNING,
                acknowledged=False,
                acknowledgedBy="",
            )
            with self.assertRaises(asyncio.TimeoutError):
                await self.remote.evt_alarm.next(flush=False, timeout=NODATA_TIMEOUT)

    async def test_mute(self):
        """Test the mute and unmute command."""
        async with self.make_csc(
            config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY
        ):
            await salobj.set_summary_state(
                self.remote, state=salobj.State.ENABLED, settingsToApply="enabled.yaml"
            )
            nrules = len(self.csc.model.rules)

            user1 = "test_mute 1"
            # Mute all alarms for a short time,
            # then wait for them to unmute themselves.
            await self.remote.cmd_mute.set_start(
                name="Enabled.*",
                duration=0.1,
                severity=AlarmSeverity.SERIOUS,
                mutedBy=user1,
                timeout=STD_TIMEOUT,
            )

            # The first batch of alarm events should be for the muted alarms.
            muted_names = set()
            while len(muted_names) < nrules:
                data = await self.assert_next_alarm(
                    mutedSeverity=AlarmSeverity.SERIOUS, mutedBy=user1
                )
                if data.name in muted_names:
                    raise self.fail(f"Duplicate alarm event for muting {data.name}")
                muted_names.add(data.name)

            # The next batch of alarm events should be for the unmuted alarms.
            unmuted_names = set()
            while len(unmuted_names) < nrules:
                data = await self.assert_next_alarm(
                    mutedSeverity=AlarmSeverity.NONE, mutedBy=""
                )
                if data.name in unmuted_names:
                    raise self.fail(
                        f"Duplicate alarm event for auto-unmuting {data.name}"
                    )
                unmuted_names.add(data.name)

            # Now mute one rule for a long time, then explicitly unmute it.
            user2 = "test_mute 2"
            full_name = "Enabled.ScriptQueue:2"
            self.assertIn(full_name, self.csc.model.rules)
            await self.remote.cmd_mute.set_start(
                name=full_name,
                duration=5,
                severity=AlarmSeverity.SERIOUS,
                mutedBy=user2,
                timeout=STD_TIMEOUT,
            )
            await self.assert_next_alarm(
                name=full_name, mutedSeverity=AlarmSeverity.SERIOUS, mutedBy=user2
            )
            # There should be the only alarm event from the mute command.
            with self.assertRaises(asyncio.TimeoutError):
                await self.remote.evt_alarm.next(flush=False, timeout=NODATA_TIMEOUT)

            await self.remote.cmd_unmute.set_start(name=full_name, timeout=STD_TIMEOUT)
            await self.assert_next_alarm(
                name=full_name, mutedSeverity=AlarmSeverity.NONE, mutedBy=""
            )
            # There should be the only alarm event from the unmute command.
            with self.assertRaises(asyncio.TimeoutError):
                await self.remote.evt_alarm.next(flush=False, timeout=1)

    async def test_settings_required(self):
        """Test that the command line parser requires --settings
        if --state is enabled or disabled.
        """
        original_argv = sys.argv[:]
        try:
            for state_name in ("disabled", "enabled"):
                sys.argv = [original_argv[0], "run_watcher.py", "--state", state_name]
                with self.assertRaises(SystemExit):
                    await watcher.WatcherCsc.make_from_cmd_line(index=None)
        finally:
            sys.argv = original_argv

    async def test_unacknowledge(self):
        """Test the unacknowledge command."""
        user = "test_unacknowledge"
        async with self.make_csc(
            config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY
        ):
            await salobj.set_summary_state(
                self.remote,
                state=salobj.State.ENABLED,
                settingsToApply="two_scriptqueue_enabled.yaml",
            )

            alarm_name1 = "Enabled.ScriptQueue:1"
            alarm_name2 = "Enabled.ScriptQueue:2"
            self.assertEqual(len(self.csc.model.rules), 2)
            self.assertEqual(list(self.csc.model.rules), [alarm_name1, alarm_name2])

            # Make a summary state writer for alarm 1.
            sq1_salinfo = salobj.SalInfo(
                domain=self.csc.domain, name="ScriptQueue", index=1
            )
            sq1_state = salobj.topics.ControllerEvent(
                salinfo=sq1_salinfo, name="summaryState"
            )

            # Send alarm 1 to severity warning.
            sq1_state.set_put(summaryState=salobj.State.DISABLED, force_output=True)
            await self.assert_next_alarm(
                name=alarm_name1,
                severity=AlarmSeverity.WARNING,
                maxSeverity=AlarmSeverity.WARNING,
                acknowledged=False,
                acknowledgedBy="",
            )

            # Unacknowledge both alarms;
            # this should not trigger an alarm event
            # because alarm 1 is not acknowledged
            # and alarm 2 is in nominal state
            await self.remote.cmd_unacknowledge.set_start(name=".*")
            with self.assertRaises(asyncio.TimeoutError):
                await self.remote.evt_alarm.next(flush=False, timeout=NODATA_TIMEOUT)

            # Unacknowledge an acknowledged alarm and check the alarm event.
            await self.remote.cmd_acknowledge.set_start(
                name=alarm_name1, severity=AlarmSeverity.WARNING, acknowledgedBy=user
            )
            await self.assert_next_alarm(
                name=alarm_name1,
                severity=AlarmSeverity.WARNING,
                maxSeverity=AlarmSeverity.WARNING,
                acknowledged=True,
                acknowledgedBy=user,
            )

            await self.remote.cmd_unacknowledge.set_start(name=alarm_name1)
            await self.assert_next_alarm(
                name=alarm_name1,
                severity=AlarmSeverity.WARNING,
                maxSeverity=AlarmSeverity.WARNING,
                acknowledged=False,
                acknowledgedBy="",
            )

            # Unacknowledge a reset alarm;
            # this should not trigger an alarm event.
            sq1_state.set_put(summaryState=salobj.State.ENABLED, force_output=True)
            await self.assert_next_alarm(
                name=alarm_name1,
                severity=AlarmSeverity.NONE,
                maxSeverity=AlarmSeverity.WARNING,
            )

            await self.remote.cmd_acknowledge.set_start(
                name=alarm_name1, severity=AlarmSeverity.WARNING, acknowledgedBy=user
            )
            await self.assert_next_alarm(
                name=alarm_name1,
                severity=AlarmSeverity.NONE,
                maxSeverity=AlarmSeverity.NONE,
                acknowledged=True,
                acknowledgedBy=user,
            )

            await self.remote.cmd_unacknowledge.set_start(name=alarm_name1)
            with self.assertRaises(asyncio.TimeoutError):
                await self.remote.evt_alarm.next(flush=False, timeout=NODATA_TIMEOUT)


if __name__ == "__main__":
    unittest.main()
