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
import shutil
import unittest

import asynctest

from lsst.ts import salobj
from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts import watcher

STD_TIMEOUT = 2  # standard command timeout (sec)
NODATA_TIMEOUT = 1  # timeout when no data is expected (sec)
LONG_TIMEOUT = 20  # timeout for starting SAL components (sec)
TEST_CONFIG_DIR = pathlib.Path(__file__).parents[1] / "tests" / "data" / "config"


class CscTestCase(asynctest.TestCase):
    def setUp(self):
        salobj.test_utils.set_random_lsst_dds_domain()
        self.csc = None
        self.remote = None

    async def tearDown(self):
        if self.remote is not None:
            await self.remote.close()
        if self.csc is not None:
            await self.csc.close()

    async def make_csc(self, config_dir):
        """Make a Watcher CSC and remote and wait for them to start.
        """
        self.csc = watcher.WatcherCsc(config_dir=config_dir)
        self.remote = salobj.Remote(domain=self.csc.domain, name="Watcher", index=0)
        await self.csc.start_task
        await self.remote.start_task

    async def assert_next_alarm(self, name=None, severity=None, maxSeverity=None,
                                acknowledged=None, acknowledgedBy=None,
                                mutedSeverity=None, mutedBy=None, timeout=STD_TIMEOUT):
        """Wait for the next alarm event and check its fields.

        Return the alarm data, in case you want to do anything else with it
        (such as access its name).
        """
        data = await self.remote.evt_alarm.next(flush=False, timeout=timeout)
        if name is not None:
            self.assertEqual(data.name, name)
        if severity is not None:
            self.assertEqual(data.severity, severity)
        if maxSeverity is not None:
            self.assertEqual(data.maxSeverity, maxSeverity)
        if acknowledged is not None:
            if acknowledged:
                self.assertTrue(data.acknowledged)
            else:
                self.assertFalse(data.acknowledged)
        if acknowledgedBy is not None:
            self.assertEqual(data.acknowledgedBy, acknowledgedBy)
        if mutedSeverity is not None:
            self.assertEqual(data.mutedSeverity, mutedSeverity)
        if mutedBy is not None:
            self.assertEqual(data.mutedBy, mutedBy)
        return data

    async def test_initial_info(self):
        await self.make_csc(config_dir=TEST_CONFIG_DIR)
        state = await self.remote.evt_summaryState.next(flush=False, timeout=LONG_TIMEOUT)
        self.assertEqual(state.summaryState, salobj.State.STANDBY)

        self.assertIsNone(self.csc.model)

        await salobj.set_summary_state(self.remote, salobj.State.ENABLED,
                                       settingsToApply="two_scriptqueue_enabled.yaml")

        state = await self.remote.evt_summaryState.next(flush=False, timeout=STD_TIMEOUT)
        self.assertEqual(state.summaryState, salobj.State.DISABLED)
        state = await self.remote.evt_summaryState.next(flush=False, timeout=STD_TIMEOUT)
        self.assertEqual(state.summaryState, salobj.State.ENABLED)

        self.assertIsInstance(self.csc.model, watcher.Model)
        rule_names = list(self.csc.model.rules)
        expected_rule_names = [f"Enabled.ScriptQueue:{index}" for index in (1, 2)]
        self.assertEqual(rule_names, expected_rule_names)

    async def test_default_config_dir(self):
        await self.make_csc(config_dir=None)
        self.assertEqual(self.csc.summary_state, salobj.State.STANDBY)

        desired_config_pkg_name = "ts_config_ocs"
        desired_config_env_name = desired_config_pkg_name.upper() + "_DIR"
        desird_config_pkg_dir = os.environ[desired_config_env_name]
        desired_config_dir = pathlib.Path(desird_config_pkg_dir) / "Watcher/v1"
        self.assertEqual(self.csc.get_config_pkg(), desired_config_pkg_name)
        self.assertEqual(self.csc.config_dir, desired_config_dir)

    async def test_configuration_invalid(self):
        await self.make_csc(config_dir=TEST_CONFIG_DIR)
        self.assertEqual(self.csc.summary_state, salobj.State.STANDBY)
        state = await self.remote.evt_summaryState.next(flush=False, timeout=LONG_TIMEOUT)
        self.assertEqual(state.summaryState, salobj.State.STANDBY)

        invalid_files = glob.glob(str(TEST_CONFIG_DIR / "invalid_*.yaml"))
        bad_config_names = [os.path.basename(name) for name in invalid_files]
        for bad_config_name in bad_config_names:
            with self.subTest(bad_config_name=bad_config_name):
                self.remote.cmd_start.set(settingsToApply=bad_config_name)
                with salobj.test_utils.assertRaisesAckError():
                    await self.remote.cmd_start.start(timeout=STD_TIMEOUT)

    async def test_operation(self):
        """Run the watcher with a few rules and one disabled SAL component."""
        await self.make_csc(config_dir=TEST_CONFIG_DIR)
        self.assertEqual(self.csc.summary_state, salobj.State.STANDBY)
        state = await self.remote.evt_summaryState.next(flush=False, timeout=LONG_TIMEOUT)
        self.assertEqual(state.summaryState, salobj.State.STANDBY)

        await salobj.set_summary_state(self.remote, state=salobj.State.ENABLED,

                                       settingsToApply="enabled.yaml")
        atdome_alarm_name = "Enabled.ATDome:0"
        scriptqueue_alarm_name = "Enabled.ScriptQueue:2"

        # Check that disabled_sal_components eliminated a rule.
        self.assertEqual(len(self.csc.model.rules), 2)
        self.assertEqual(list(self.csc.model.rules),
                         [atdome_alarm_name, scriptqueue_alarm_name])

        # Make summary state writers for CSCs in `enabled.yaml`.
        atdome_salinfo = salobj.SalInfo(domain=self.csc.domain, name="ATDome", index=0)
        atdome_state = salobj.topics.ControllerEvent(salinfo=atdome_salinfo, name="summaryState")

        atdome_state.set_put(summaryState=salobj.State.DISABLED, force_output=True)
        await self.assert_next_alarm(name=atdome_alarm_name,
                                     severity=AlarmSeverity.WARNING,
                                     maxSeverity=AlarmSeverity.WARNING,
                                     acknowledged=False,
                                     acknowledgedBy="")

        atdome_state.set_put(summaryState=salobj.State.FAULT, force_output=True)
        await self.assert_next_alarm(name=atdome_alarm_name,
                                     severity=AlarmSeverity.SERIOUS,
                                     maxSeverity=AlarmSeverity.SERIOUS,
                                     acknowledged=False,
                                     acknowledgedBy="")

        user = "test_operation"
        await self.remote.cmd_acknowledge.set_start(name=atdome_alarm_name,
                                                    severity=AlarmSeverity.SERIOUS,
                                                    acknowledgedBy=user)
        await self.assert_next_alarm(name=atdome_alarm_name,
                                     severity=AlarmSeverity.SERIOUS,
                                     maxSeverity=AlarmSeverity.SERIOUS,
                                     acknowledged=True,
                                     acknowledgedBy=user)

        # Set the state to ENABLED; this should reset the alarm.
        atdome_state.set_put(summaryState=salobj.State.ENABLED, force_output=True)
        await self.assert_next_alarm(name=atdome_alarm_name,
                                     severity=AlarmSeverity.NONE,
                                     maxSeverity=AlarmSeverity.NONE,
                                     acknowledged=False,
                                     acknowledgedBy="")

    async def test_show_alarms(self):
        """Test the showAlarms command."""
        await self.make_csc(config_dir=TEST_CONFIG_DIR)
        self.assertEqual(self.csc.summary_state, salobj.State.STANDBY)
        state = await self.remote.evt_summaryState.next(flush=False, timeout=LONG_TIMEOUT)
        self.assertEqual(state.summaryState, salobj.State.STANDBY)

        await salobj.set_summary_state(self.remote, state=salobj.State.ENABLED,
                                       settingsToApply="enabled.yaml")

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
        atdome_salinfo = salobj.SalInfo(domain=self.csc.domain, name="ATDome", index=0)
        atdome_state = salobj.topics.ControllerEvent(salinfo=atdome_salinfo, name="summaryState")
        scriptqueue_salinfo = salobj.SalInfo(domain=self.csc.domain, name="ScriptQueue", index=2)
        scriptqueue_state = salobj.topics.ControllerEvent(salinfo=scriptqueue_salinfo,
                                                          name="summaryState")

        # Fire the ATDome alarm.
        atdome_state.set_put(summaryState=salobj.State.DISABLED, force_output=True)
        await self.assert_next_alarm(name=atdome_alarm_name,
                                     severity=AlarmSeverity.WARNING,
                                     maxSeverity=AlarmSeverity.WARNING,
                                     acknowledged=False,
                                     acknowledgedBy="")

        # Fire the ScriptQueue:2 alarm.
        scriptqueue_state.set_put(summaryState=salobj.State.DISABLED, force_output=True)
        await self.assert_next_alarm(name=scriptqueue_alarm_name,
                                     severity=AlarmSeverity.WARNING,
                                     maxSeverity=AlarmSeverity.WARNING,
                                     acknowledged=False,
                                     acknowledgedBy="")

        # We expect no more alarm events (yet).
        with self.assertRaises(asyncio.TimeoutError):
            await self.remote.evt_alarm.next(flush=False, timeout=NODATA_TIMEOUT)

        # Send the showAlarms command. This should trigger the same
        # two alarm events that we have already seen (in either order).
        await self.remote.cmd_showAlarms.start(timeout=STD_TIMEOUT)
        alarm_names = []
        for i in range(2):
            alarm = await self.assert_next_alarm(severity=AlarmSeverity.WARNING,
                                                 maxSeverity=AlarmSeverity.WARNING,
                                                 acknowledged=False)
            alarm_names.append(alarm.name)
        self.assertEqual(set(alarm_names), set(("Enabled.ATDome:0", "Enabled.ScriptQueue:2")))
        with self.assertRaises(asyncio.TimeoutError):
            await self.remote.evt_alarm.next(flush=False, timeout=NODATA_TIMEOUT)

        # Acknowledge the ATDome alarm.
        user = "test_show_alarms"
        await self.remote.cmd_acknowledge.set_start(name=atdome_alarm_name,
                                                    severity=AlarmSeverity.WARNING,
                                                    acknowledgedBy=user)
        await self.assert_next_alarm(name=atdome_alarm_name,
                                     severity=AlarmSeverity.WARNING,
                                     maxSeverity=AlarmSeverity.WARNING,
                                     acknowledged=True,
                                     acknowledgedBy=user)

        # Set ATDome state to ENABLED; this should reset the alarm.
        atdome_state.set_put(summaryState=salobj.State.ENABLED, force_output=True)
        await self.assert_next_alarm(name=atdome_alarm_name,
                                     severity=AlarmSeverity.NONE,
                                     maxSeverity=AlarmSeverity.NONE,
                                     acknowledged=False,
                                     acknowledgedBy="")

        # Send the showAlarms command again. This should trigger
        # just one alarm: Enabled.ScriptQueue:2.
        await self.remote.cmd_showAlarms.start(timeout=STD_TIMEOUT)
        await self.assert_next_alarm(name=scriptqueue_alarm_name,
                                     severity=AlarmSeverity.WARNING,
                                     maxSeverity=AlarmSeverity.WARNING,
                                     acknowledged=False,
                                     acknowledgedBy="")
        with self.assertRaises(asyncio.TimeoutError):
            await self.remote.evt_alarm.next(flush=False, timeout=NODATA_TIMEOUT)

    async def test_mute(self):
        """Test the mute and unmute command."""
        await self.make_csc(config_dir=TEST_CONFIG_DIR)
        await salobj.set_summary_state(self.remote, state=salobj.State.ENABLED,
                                       settingsToApply="enabled.yaml")
        nrules = len(self.csc.model.rules)

        user1 = "test_mute 1"
        # Mute all alarms for a short time,
        # then wait for them to unmute themselves.
        await self.remote.cmd_mute.set_start(name="Enabled.*",
                                             duration=0.1,
                                             severity=AlarmSeverity.SERIOUS,
                                             mutedBy=user1,
                                             timeout=STD_TIMEOUT)

        # The first batch of alarm events should be for the muted alarms.
        muted_names = set()
        while len(muted_names) < nrules:
            data = await self.assert_next_alarm(mutedSeverity=AlarmSeverity.SERIOUS,
                                                mutedBy=user1)
            if data.name in muted_names:
                raise self.fail(f"Duplicate alarm event for muting {data.name}")
            muted_names.add(data.name)

        # The next batch of alarm events should be for the unmuted alarms.
        unmuted_names = set()
        while len(unmuted_names) < nrules:
            data = await self.assert_next_alarm(mutedSeverity=AlarmSeverity.NONE,
                                                mutedBy="")
            if data.name in unmuted_names:
                raise self.fail(f"Duplicate alarm event for auto-unmuting {data.name}")
            unmuted_names.add(data.name)

        # Now mute one rule for a long time, then explicitly unmute it.
        user2 = "test_mute 2"
        full_name = "Enabled.ScriptQueue:2"
        self.assertIn(full_name, self.csc.model.rules)
        await self.remote.cmd_mute.set_start(name=full_name,
                                             duration=5,
                                             severity=AlarmSeverity.SERIOUS,
                                             mutedBy=user2,
                                             timeout=STD_TIMEOUT)
        await self.assert_next_alarm(name=full_name,
                                     mutedSeverity=AlarmSeverity.SERIOUS,
                                     mutedBy=user2)
        # There should be the only alarm event from the mute command.
        with self.assertRaises(asyncio.TimeoutError):
            await self.remote.evt_alarm.next(flush=False, timeout=NODATA_TIMEOUT)

        await self.remote.cmd_unmute.set_start(name=full_name, timeout=STD_TIMEOUT)
        await self.assert_next_alarm(name=full_name,
                                     mutedSeverity=AlarmSeverity.NONE,
                                     mutedBy="")
        # There should be the only alarm event from the unmute command.
        with self.assertRaises(asyncio.TimeoutError):
            await self.remote.evt_alarm.next(flush=False, timeout=1)

    async def test_run(self):
        salobj.test_utils.set_random_lsst_dds_domain()
        exe_name = "run_watcher.py"
        exe_path = shutil.which(exe_name)
        if exe_path is None:
            self.fail(f"Could not find bin script {exe_name}; did you setup and scons this package?")

        process = await asyncio.create_subprocess_exec(exe_name)
        try:
            async with salobj.Domain() as domain:
                remote = salobj.Remote(domain=domain, name="Watcher", index=0)
                summaryState_data = await remote.evt_summaryState.next(flush=False, timeout=LONG_TIMEOUT)
                self.assertEqual(summaryState_data.summaryState, salobj.State.STANDBY)

                ack = await remote.cmd_exitControl.start(timeout=STD_TIMEOUT)
                self.assertEqual(ack.ack, salobj.SalRetCode.CMD_COMPLETE)
                summaryState_data = await remote.evt_summaryState.next(flush=False, timeout=LONG_TIMEOUT)
                self.assertEqual(summaryState_data.summaryState, salobj.State.OFFLINE)

                await asyncio.wait_for(process.wait(), 5)
        except Exception:
            if process.returncode is None:
                process.terminate()
            raise


if __name__ == "__main__":
    unittest.main()
