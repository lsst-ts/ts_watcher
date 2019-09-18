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

from lsst.ts import salobj
from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts import watcher

STD_TIMEOUT = 2  # standard command timeout (sec)
LONG_TIMEOUT = 20  # timeout for starting SAL components (sec)
TEST_CONFIG_DIR = pathlib.Path(__file__).parents[1] / "tests" / "data" / "config"


class Harness:
    def __init__(self, initial_state, config_dir=None):
        salobj.test_utils.set_random_lsst_dds_domain()
        self.csc = watcher.WatcherCsc(
            config_dir=config_dir,
            initial_state=initial_state)
        self.remote = salobj.Remote(domain=self.csc.domain, name="Watcher", index=0)

    async def __aenter__(self):
        await self.csc.start_task
        await self.remote.start_task
        return self

    async def __aexit__(self, *args):
        await self.remote.close()
        await self.csc.close()


class CscTestCase(unittest.TestCase):
    def setUp(self):
        print()

    def test_initial_info(self):

        async def doit():
            async with Harness(initial_state=salobj.State.STANDBY,
                               config_dir=TEST_CONFIG_DIR) as harness:
                state = await harness.remote.evt_summaryState.next(flush=False, timeout=LONG_TIMEOUT)
                self.assertEqual(state.summaryState, salobj.State.STANDBY)

                self.assertIsNone(harness.csc.model)

                await salobj.set_summary_state(harness.remote, salobj.State.ENABLED,
                                               settingsToApply="two_scriptqueue_enabled.yaml")

                state = await harness.remote.evt_summaryState.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(state.summaryState, salobj.State.DISABLED)
                state = await harness.remote.evt_summaryState.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(state.summaryState, salobj.State.ENABLED)

                self.assertIsInstance(harness.csc.model, watcher.Model)
                rule_names = list(harness.csc.model.rules)
                expected_rule_names = [f"Enabled.ScriptQueue:{index}" for index in (1, 2)]
                self.assertEqual(rule_names, expected_rule_names)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_default_config_dir(self):
        async def doit():
            async with Harness(initial_state=salobj.State.STANDBY) as harness:
                self.assertEqual(harness.csc.summary_state, salobj.State.STANDBY)

                desired_config_pkg_name = "ts_config_ocs"
                desired_config_env_name = desired_config_pkg_name.upper() + "_DIR"
                desird_config_pkg_dir = os.environ[desired_config_env_name]
                desired_config_dir = pathlib.Path(desird_config_pkg_dir) / "Watcher/v1"
                self.assertEqual(harness.csc.get_config_pkg(), desired_config_pkg_name)
                self.assertEqual(harness.csc.config_dir, desired_config_dir)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_configuration_invalid(self):
        async def doit():
            async with Harness(initial_state=salobj.State.STANDBY, config_dir=TEST_CONFIG_DIR) as harness:
                self.assertEqual(harness.csc.summary_state, salobj.State.STANDBY)
                state = await harness.remote.evt_summaryState.next(flush=False, timeout=LONG_TIMEOUT)
                self.assertEqual(state.summaryState, salobj.State.STANDBY)

                invalid_files = glob.glob(str(TEST_CONFIG_DIR / "invalid_*.yaml"))
                bad_config_names = [os.path.basename(name) for name in invalid_files]
                for bad_config_name in bad_config_names:
                    with self.subTest(bad_config_name=bad_config_name):
                        harness.remote.cmd_start.set(settingsToApply=bad_config_name)
                        with salobj.test_utils.assertRaisesAckError():
                            await harness.remote.cmd_start.start(timeout=STD_TIMEOUT)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_operation(self):
        """Run the watcher with a few rules and one disabled SAL component."""
        async def doit():
            async with Harness(initial_state=salobj.State.STANDBY, config_dir=TEST_CONFIG_DIR) as harness:
                self.assertEqual(harness.csc.summary_state, salobj.State.STANDBY)
                state = await harness.remote.evt_summaryState.next(flush=False, timeout=LONG_TIMEOUT)
                self.assertEqual(state.summaryState, salobj.State.STANDBY)

                await salobj.set_summary_state(harness.remote, state=salobj.State.ENABLED,
                                               settingsToApply="enabled.yaml")

                # check that disabled_sal_components eliminated a rule
                self.assertEqual(len(harness.csc.model.rules), 2)
                self.assertEqual(list(harness.csc.model.rules),
                                 ["Enabled.ATDome:0", "Enabled.ScriptQueue:2"])

                # make summary state writers for CSCs in `enabled.yaml`
                atdome_salinfo = salobj.SalInfo(domain=harness.csc.domain, name="ATDome", index=0)
                atdome_state = salobj.topics.ControllerEvent(salinfo=atdome_salinfo, name="summaryState")
                atdome_state.set_put(summaryState=salobj.State.DISABLED, force_output=True)
                alarm = await harness.remote.evt_alarm.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(alarm.severity, AlarmSeverity.WARNING)
                self.assertEqual(alarm.maxSeverity, AlarmSeverity.WARNING)
                self.assertFalse(alarm.acknowledged)

                atdome_state.set_put(summaryState=salobj.State.FAULT, force_output=True)
                alarm = await harness.remote.evt_alarm.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(alarm.severity, AlarmSeverity.SERIOUS)
                self.assertEqual(alarm.maxSeverity, AlarmSeverity.SERIOUS)
                self.assertFalse(alarm.acknowledged)

                user = "time_operation"
                await harness.remote.cmd_acknowledge.set_start(name="Enabled.ATDome:0",
                                                               severity=AlarmSeverity.SERIOUS,
                                                               acknowledgedBy=user)
                alarm = await harness.remote.evt_alarm.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(alarm.severity, AlarmSeverity.SERIOUS)
                self.assertEqual(alarm.maxSeverity, AlarmSeverity.SERIOUS)
                self.assertTrue(alarm.acknowledged)
                self.assertEqual(alarm.acknowledgedBy, user)

                # set the state to ENABLED; this should reset the alarm
                atdome_state.set_put(summaryState=salobj.State.ENABLED, force_output=True)
                alarm = await harness.remote.evt_alarm.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(alarm.severity, AlarmSeverity.NONE)
                self.assertEqual(alarm.maxSeverity, AlarmSeverity.NONE)
                self.assertFalse(alarm.acknowledged)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_run(self):
        salobj.test_utils.set_random_lsst_dds_domain()
        exe_name = "run_watcher.py"
        exe_path = shutil.which(exe_name)
        if exe_path is None:
            self.fail(f"Could not find bin script {exe_name}; did you setup and scons this package?")

        async def doit():
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

        asyncio.get_event_loop().run_until_complete(doit())


if __name__ == "__main__":
    unittest.main()