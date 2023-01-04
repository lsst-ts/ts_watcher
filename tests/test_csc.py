# This file is part of ts_Watcher.
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

import asyncio
import glob
import json
import os
import pathlib
import pytest
import sys
import unittest

from lsst.ts import salobj
from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts import utils
from lsst.ts import watcher

STD_TIMEOUT = 2  # standard command timeout (sec)
NODATA_TIMEOUT = 1  # timeout when no data is expected (sec)
TEST_CONFIG_DIR = (
    pathlib.Path(__file__).parents[1] / "tests" / "data" / "config" / "csc"
)

# Time delta to compensate for clock jitter on Docker on macOS (sec).
TIME_EPSILON = 0.1


class CscTestCase(salobj.BaseCscTestCase, unittest.IsolatedAsyncioTestCase):
    def basic_make_csc(self, initial_state, config_dir, simulation_mode):
        assert initial_state == salobj.State.STANDBY
        assert simulation_mode == 0
        return watcher.WatcherCsc(config_dir=config_dir)

    async def assert_next_alarm(
        self,
        timeout=STD_TIMEOUT,
        **kwargs,
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
            assert getattr(data, name) == value
        return data

    async def test_bin_script(self):
        await self.check_bin_script(
            name="Watcher",
            index=None,
            exe_name="run_watcher",
        )

    async def test_initial_info(self):
        async with self.make_csc(
            config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY
        ):
            await self.assert_next_summary_state(salobj.State.STANDBY)
            assert self.csc.model is None

            await self.assert_next_sample(
                topic=self.remote.evt_softwareVersions,
                cscVersion=watcher.__version__,
                subsystemVersions="",
            )

            await salobj.set_summary_state(
                self.remote,
                salobj.State.ENABLED,
                override="two_scriptqueue_enabled.yaml",
            )
            await self.assert_next_summary_state(salobj.State.DISABLED)
            await self.assert_next_summary_state(salobj.State.ENABLED)
            assert isinstance(self.csc.model, watcher.Model)
            rule_names = list(self.csc.model.rules)
            expected_rule_names = [f"Enabled.ScriptQueue:{index}" for index in (1, 2)]
            assert rule_names == expected_rule_names

            # Check that escalation info is not set for the first rule
            # and is set for the second rule.
            alarm1 = self.csc.model.rules[expected_rule_names[0]].alarm
            alarm2 = self.csc.model.rules[expected_rule_names[1]].alarm
            assert alarm1.escalation_responders == []
            assert alarm1.escalation_delay == 0
            assert alarm1.timestamp_escalate == 0
            assert not alarm1.do_escalate
            assert alarm1.escalated_id == ""
            assert alarm2.escalation_responders == [{"name": "stella", "type": "team"}]
            assert alarm2.escalation_delay == 0.11
            assert alarm2.timestamp_escalate == 0
            assert not alarm2.do_escalate
            assert alarm2.escalated_id == ""

    async def test_default_config_dir(self):
        async with self.make_csc(config_dir=None, initial_state=salobj.State.STANDBY):
            desired_config_pkg_name = "ts_config_ocs"
            desired_config_env_name = desired_config_pkg_name.upper() + "_DIR"
            desird_config_pkg_dir = os.environ[desired_config_env_name]
            desired_config_dir = pathlib.Path(desird_config_pkg_dir) / "Watcher/v4"
            assert self.csc.get_config_pkg() == desired_config_pkg_name
            assert self.csc.config_dir == desired_config_dir

    async def test_configuration_invalid(self):
        async with self.make_csc(
            config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY
        ):
            invalid_files = glob.glob(str(TEST_CONFIG_DIR / "invalid_*.yaml"))
            # Test the invalid files and a blank override
            # (since the schema doesn't have a usable default).
            bad_config_names = [os.path.basename(name) for name in invalid_files]
            for bad_config_name in bad_config_names:
                with self.subTest(bad_config_name=bad_config_name):
                    with salobj.assertRaisesAckError(ack=salobj.SalRetCode.CMD_FAILED):
                        await self.remote.cmd_start.set_start(
                            configurationOverride=bad_config_name, timeout=STD_TIMEOUT
                        )

            # Check that the CSC can still be configured.
            # This also exercises specifying a rule with no configuration.
            await self.remote.cmd_start.set_start(
                configurationOverride="basic.yaml", timeout=STD_TIMEOUT
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
                override="two_scriptqueue_enabled.yaml",
            )

    async def test_escalation_success(self):
        await self.check_escalation()

    async def test_escalation_service_down(self):
        await self.check_escalation(service_down=True)

    async def test_escalation_create_fails(self):
        await self.check_escalation(create_fails=True)

    async def test_escalation_close_fails(self):
        await self.check_escalation(close_fails=True)

    async def check_escalation(
        self, service_down=False, create_fails=False, close_fails=False
    ):
        """Run the watcher with a ConfiguredSeverity rule and make sure
        the escalation fields look correct in the Alarm event.

        Parameters
        ----------
        service_down : `bool`
            Simulate the OpsGenie service being down.
        create_fails : `bool`
            Simulate the OpsGenie service rejecting the create attempt.
        close_fails : `bool`
            Simulate the OpsGenie service rejecting the close attempt.
            This should still work, just log a warning.
        """
        if service_down and create_fails:
            raise ValueError("Cannot set both service_down and create_fails")
        escalation_fails = service_down or create_fails
        with utils.modify_environ(ESCALATION_KEY="anything"):
            async with watcher.MockOpsGenie(port=0) as mock_opsgenie, self.make_csc(
                config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY
            ):
                await salobj.set_summary_state(
                    self.remote, state=salobj.State.ENABLED, override="critical.yaml"
                )
                # First test the URL from critical.yaml,
                # then overwrite it with a URL that has the correct port.
                assert self.csc.model.config.escalation_url == "http://127.0.0.1:80"
                if service_down:
                    # Try to connect to port 0, which is sure to fail.
                    # Note: the reason we run the mock OpsGenie service
                    # in this case is to simplify the code.
                    self.csc.model.config.escalation_url = "http://127.0.0.1:0"
                else:
                    self.csc.model.config.escalation_url = mock_opsgenie.url

                if create_fails:
                    mock_opsgenie.reject_next_request = True

                alarm_name1 = "test.ConfiguredSeverities.ATDome"
                alarm_name2 = "test.ConfiguredSeverities.ATCamera"
                assert list(self.csc.model.rules) == [alarm_name1, alarm_name2]

                # Alarm 1 will be escalated because it has an escalation
                # responder and the escalation delay is > 0.
                alarm1 = self.csc.model.rules[alarm_name1].alarm
                assert len(alarm1.escalation_responders) == 1
                assert alarm1.escalation_delay == pytest.approx(0.01)

                expected_escalate_to_alarm1 = json.dumps(
                    [{"name": "stella", "type": "team"}]
                )

                # Alarm 2 will never be escalated because it has no
                # escalation responders and the escalation delay is 0.
                alarm2 = self.csc.model.rules[alarm_name2].alarm
                assert len(alarm2.escalation_responders) == 0
                assert alarm2.escalation_delay == 0

                # Follow the severity sequence specified in critical.yaml,
                # but expect one extra event from ATDome (alarm 1)
                # when it goes critical, because the alarm is escalated
                # after a very short delay.
                await self.assert_next_alarm(
                    name=alarm_name1,
                    severity=AlarmSeverity.WARNING,
                    maxSeverity=AlarmSeverity.WARNING,
                    escalatedId="",
                    escalateTo=expected_escalate_to_alarm1,
                    timestampEscalate=0,
                )
                await self.assert_next_alarm(
                    name=alarm_name2,
                    severity=AlarmSeverity.SERIOUS,
                    maxSeverity=AlarmSeverity.SERIOUS,
                    escalatedId="",
                    escalateTo="[]",
                    timestampEscalate=0,
                )

                # When alarm 1 goes to CRITICAL it will be escalated
                # after a very short time (well before the next
                # severity is reported for alarm 2).
                data = await self.assert_next_alarm(
                    name=alarm_name1,
                    severity=AlarmSeverity.CRITICAL,
                    maxSeverity=AlarmSeverity.CRITICAL,
                    escalatedId="",
                    escalateTo=expected_escalate_to_alarm1,
                )
                assert data.timestampEscalate > 0
                timestamp_escalate = data.timestampEscalate
                # Alarm 1's escalation timer is now running
                # (for a very short time).
                assert not alarm1.escalation_timer_task.done()
                # The next event indicates that alarm1 has been escalated.
                data = await self.assert_next_alarm(
                    name=alarm_name1,
                    severity=AlarmSeverity.CRITICAL,
                    maxSeverity=AlarmSeverity.CRITICAL,
                    escalateTo=expected_escalate_to_alarm1,
                    timestampEscalate=timestamp_escalate,
                )
                assert alarm1.do_escalate
                assert alarm1.escalated_id != ""
                assert data.escalatedId == alarm1.escalated_id
                if escalation_fails:
                    assert alarm1.escalated_id.startswith("Failed: ")
                else:
                    assert not alarm1.escalated_id.startswith("Failed: ")
                if escalation_fails:
                    assert len(mock_opsgenie.alerts) == 0
                else:
                    assert len(mock_opsgenie.alerts) == 1
                    alert = mock_opsgenie.alerts[alarm1.escalated_id]
                    assert alert["status"] == "open"
                    assert "ATDome" in alert["message"]
                    assert alert["id"] == alarm1.escalated_id
                    saved_alert_id = alarm1.escalated_id

                # Finish the configured sequence of severities.
                await self.assert_next_alarm(
                    name=alarm_name2,
                    severity=AlarmSeverity.CRITICAL,
                    maxSeverity=AlarmSeverity.CRITICAL,
                    escalatedId="",
                    escalateTo="[]",
                    timestampEscalate=0,
                )
                # Alarm 2 is not configured to be escalated,
                # so its escalation timer should not be running.
                assert alarm2.escalation_timer_task.done()
                data = await self.assert_next_alarm(
                    name=alarm_name1,
                    severity=AlarmSeverity.WARNING,
                    maxSeverity=AlarmSeverity.CRITICAL,
                    escalateTo=expected_escalate_to_alarm1,
                    timestampEscalate=timestamp_escalate,
                )
                assert alarm1.do_escalate
                assert alarm1.escalated_id != ""
                assert data.escalatedId == alarm1.escalated_id
                if escalation_fails:
                    assert alarm1.escalated_id.startswith("Failed: ")
                else:
                    assert not alarm1.escalated_id.startswith("Failed: ")
                await self.assert_next_alarm(
                    name=alarm_name2,
                    severity=AlarmSeverity.NONE,
                    maxSeverity=AlarmSeverity.CRITICAL,
                    escalatedId="",
                    escalateTo="[]",
                    timestampEscalate=0,
                )

                # Acknowledge alarm 1. That should make the alarm
                # be de-escalated (even though the alarm severity
                # is not back to NONE).
                if close_fails:
                    mock_opsgenie.reject_next_request = True
                await self.remote.cmd_acknowledge.set_start(
                    name=alarm_name1,
                    severity=AlarmSeverity.CRITICAL,
                    acknowledgedBy="arbitrary",
                )
                await self.assert_next_alarm(
                    name=alarm_name1,
                    severity=AlarmSeverity.WARNING,
                    maxSeverity=AlarmSeverity.CRITICAL,
                    escalatedId="",
                    escalateTo=expected_escalate_to_alarm1,
                    timestampEscalate=0,
                )
                # The escalated ID should have been cleared
                # (even if de-escalation fails),
                # so use the saved alert ID to access the alert.
                assert not alarm1.do_escalate
                assert alarm1.escalated_id == ""
                if not escalation_fails:
                    assert len(mock_opsgenie.alerts) == 1
                    alert = mock_opsgenie.alerts[saved_alert_id]
                    if close_fails:
                        assert alert["status"] == "open"
                    else:
                        assert alert["status"] == "closed"
                    assert "ATDome" in alert["message"]
                    assert alert["id"] == saved_alert_id

    async def test_operation(self):
        """Run the watcher with a few rules and one disabled SAL component."""
        async with self.make_csc(
            config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY
        ), salobj.Controller(name="ATDome", write_only=True) as atdome:
            await salobj.set_summary_state(
                self.remote, state=salobj.State.ENABLED, override="enabled.yaml"
            )

            atdome_alarm_name = "Enabled.ATDome:0"
            scriptqueue_alarm_name = "Enabled.ScriptQueue:2"

            # Check that disabled_sal_components eliminated a rule.
            assert len(self.csc.model.rules) == 2
            assert list(self.csc.model.rules) == [
                atdome_alarm_name,
                scriptqueue_alarm_name,
            ]

            # Make summary state writers for CSCs in `enabled.yaml`.
            await atdome.evt_summaryState.set_write(
                summaryState=salobj.State.DISABLED, force_output=True
            )
            await self.assert_next_alarm(
                name=atdome_alarm_name,
                severity=AlarmSeverity.WARNING,
                maxSeverity=AlarmSeverity.WARNING,
                acknowledged=False,
                acknowledgedBy="",
            )

            await atdome.evt_summaryState.set_write(
                summaryState=salobj.State.FAULT, force_output=True
            )
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
            await atdome.evt_summaryState.set_write(
                summaryState=salobj.State.ENABLED, force_output=True
            )
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
        ), salobj.Controller(name="ATDome", write_only=True) as atdome:
            await salobj.set_summary_state(
                self.remote,
                state=salobj.State.ENABLED,
                override="enabled_short_auto_delays.yaml",
            )

            # Check the values encoded in the yaml config file.
            expected_auto_acknowledge_delay = 0.51
            expected_auto_unacknowledge_delay = 0.52
            assert self.csc.model.config.auto_acknowledge_delay == pytest.approx(
                expected_auto_acknowledge_delay
            )
            assert self.csc.model.config.auto_unacknowledge_delay == pytest.approx(
                expected_auto_unacknowledge_delay
            )

            atdome_alarm_name = "Enabled.ATDome:0"

            # Make the ATDome alarm stale.
            await atdome.evt_summaryState.set_write(
                summaryState=salobj.State.DISABLED, force_output=True
            )
            await self.assert_next_alarm(
                name=atdome_alarm_name,
                severity=AlarmSeverity.WARNING,
                maxSeverity=AlarmSeverity.WARNING,
                acknowledged=False,
                acknowledgedBy="",
            )

            await atdome.evt_summaryState.set_write(
                summaryState=salobj.State.ENABLED, force_output=True
            )
            await self.assert_next_alarm(
                name=atdome_alarm_name,
                severity=AlarmSeverity.NONE,
                maxSeverity=AlarmSeverity.WARNING,
                acknowledged=False,
                acknowledgedBy="",
            )

            # Wait for automatic acknowledgement.
            t0 = utils.current_tai()
            alarm = await self.assert_next_alarm(
                name=atdome_alarm_name,
                severity=AlarmSeverity.NONE,
                maxSeverity=AlarmSeverity.NONE,
                acknowledged=True,
                acknowledgedBy="automatic",
            )
            dt0 = utils.current_tai() - t0
            assert alarm.timestampAcknowledged >= t0 - TIME_EPSILON
            assert dt0 >= expected_auto_acknowledge_delay - TIME_EPSILON

            # Make the ATDome alarm acknowledged and not stale
            await atdome.evt_summaryState.set_write(
                summaryState=salobj.State.DISABLED, force_output=True
            )
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
            t1 = utils.current_tai()
            alarm = await self.assert_next_alarm(
                name=atdome_alarm_name,
                severity=AlarmSeverity.WARNING,
                maxSeverity=AlarmSeverity.WARNING,
                acknowledged=False,
                acknowledgedBy="",
            )
            dt1 = utils.current_tai() - t1
            assert alarm.timestampAcknowledged >= t1 - TIME_EPSILON
            assert dt1 >= expected_auto_unacknowledge_delay - TIME_EPSILON

    async def test_show_alarms(self):
        """Test the showAlarms command."""
        async with self.make_csc(
            config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY
        ), salobj.Controller(
            name="ATDome", write_only=True
        ) as atdome, salobj.Controller(
            name="ScriptQueue", index=2, write_only=True
        ) as script_queue2:
            await salobj.set_summary_state(
                self.remote, state=salobj.State.ENABLED, override="enabled.yaml"
            )

            atdome_alarm_name = "Enabled.ATDome:0"
            scriptqueue_alarm_name = "Enabled.ScriptQueue:2"

            # All alarms should be nominal, so showAlarms should output
            # no alarm events.
            for rule in self.csc.model.rules.values():
                assert rule.alarm.nominal
            await self.remote.cmd_showAlarms.start(timeout=STD_TIMEOUT)
            with pytest.raises(asyncio.TimeoutError):
                await self.remote.evt_alarm.next(flush=False, timeout=NODATA_TIMEOUT)

            # Fire the ATDome alarm.
            await atdome.evt_summaryState.set_write(
                summaryState=salobj.State.DISABLED, force_output=True
            )
            await self.assert_next_alarm(
                name=atdome_alarm_name,
                severity=AlarmSeverity.WARNING,
                maxSeverity=AlarmSeverity.WARNING,
                acknowledged=False,
                acknowledgedBy="",
            )

            # Fire the ScriptQueue:2 alarm.
            await script_queue2.evt_summaryState.set_write(
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
            with pytest.raises(asyncio.TimeoutError):
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
            assert set(alarm_names) == set(
                ("Enabled.ATDome:0", "Enabled.ScriptQueue:2")
            )
            with pytest.raises(asyncio.TimeoutError):
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
            await atdome.evt_summaryState.set_write(
                summaryState=salobj.State.ENABLED, force_output=True
            )
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
            with pytest.raises(asyncio.TimeoutError):
                await self.remote.evt_alarm.next(flush=False, timeout=NODATA_TIMEOUT)

    async def test_mute(self):
        """Test the mute and unmute command."""
        async with self.make_csc(
            config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY
        ):
            await salobj.set_summary_state(
                self.remote, state=salobj.State.ENABLED, override="enabled.yaml"
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
            assert full_name in self.csc.model.rules
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
            with pytest.raises(asyncio.TimeoutError):
                await self.remote.evt_alarm.next(flush=False, timeout=NODATA_TIMEOUT)

            await self.remote.cmd_unmute.set_start(name=full_name, timeout=STD_TIMEOUT)
            await self.assert_next_alarm(
                name=full_name, mutedSeverity=AlarmSeverity.NONE, mutedBy=""
            )
            # There should be the only alarm event from the unmute command.
            with pytest.raises(asyncio.TimeoutError):
                await self.remote.evt_alarm.next(flush=False, timeout=1)

    async def test_settings_required(self):
        """Test that the command line parser requires --settings
        if --state is enabled or disabled.
        """
        original_argv = sys.argv[:]
        try:
            for state_name in ("disabled", "enabled"):
                sys.argv = [original_argv[0], "run_watcher", "--state", state_name]
                with pytest.raises(SystemExit):
                    await watcher.WatcherCsc.make_from_cmd_line(index=None)
        finally:
            sys.argv = original_argv

    async def test_unacknowledge(self):
        """Test the unacknowledge command."""
        user = "test_unacknowledge"
        async with self.make_csc(
            config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY
        ), salobj.Controller(
            name="ScriptQueue", index=1, write_only=True
        ) as script_queue1:
            await salobj.set_summary_state(
                self.remote,
                state=salobj.State.ENABLED,
                override="two_scriptqueue_enabled.yaml",
            )

            alarm_name1 = "Enabled.ScriptQueue:1"
            alarm_name2 = "Enabled.ScriptQueue:2"
            assert len(self.csc.model.rules) == 2
            assert list(self.csc.model.rules) == [alarm_name1, alarm_name2]

            # Send alarm 1 to severity warning.
            await script_queue1.evt_summaryState.set_write(
                summaryState=salobj.State.DISABLED, force_output=True
            )
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
            with pytest.raises(asyncio.TimeoutError):
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
            await script_queue1.evt_summaryState.set_write(
                summaryState=salobj.State.ENABLED, force_output=True
            )
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
            with pytest.raises(asyncio.TimeoutError):
                await self.remote.evt_alarm.next(flush=False, timeout=NODATA_TIMEOUT)
