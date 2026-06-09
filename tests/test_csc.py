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
import logging
import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import pytest

from lsst.ts import salobj, utils, watcher
from lsst.ts.xml.enums.Watcher import AlarmSeverity

STD_TIMEOUT = 20  # standard command timeout (sec)
NODATA_TIMEOUT = 1  # timeout when no data is expected (sec)
TEST_CONFIG_DIR = pathlib.Path(__file__).parents[1] / "tests" / "data" / "config" / "csc"

# Time delta to compensate for clock jitter on Docker on macOS (sec).
TIME_EPSILON = 0.1


class CscTestCase(salobj.BaseCscTestCase, unittest.IsolatedAsyncioTestCase):
    def basic_make_csc(self, initial_state, config_dir, simulation_mode, **kwargs):
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
        data = await self.assert_next_sample(self.remote.evt_alarm, flush=False, timeout=timeout)

        for name, value_expected in kwargs.items():
            value_current = getattr(data, name)
            assert value_current == value_expected, f"{name}: {value_current} expected {value_expected}"
        return data

    async def check_all_alarms_events_are_none(self):
        """Check that alarm events are seen for all rules and are
        all severity NONE.

        This is usually true after enabling the CSC, but only if
        data that topic-callback-based rules need is compatible
        with the alarm being NONE.
        """
        alarm_names = set()
        for index, alarm_name in enumerate(self.csc.alarms_info):
            self.csc.log.debug(f"Waiting for alarm {index} of {len(self.csc.alarms_info)}.")
            alarm_names.add(alarm_name)
            await self.assert_next_alarm(
                severity=AlarmSeverity.NONE,
                maxSeverity=AlarmSeverity.NONE,
                acknowledged=False,
                acknowledgedBy="",
            )
        assert self.csc.alarms_info.keys() == alarm_names

    async def test_bin_script(self):
        await self.check_bin_script(
            name="Watcher",
            index=None,
            exe_name="run_watcher",
        )

    async def test_initial_info(self):
        async with self.make_csc(config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY):
            await self.assert_next_summary_state(salobj.State.STANDBY)

            await self.assert_next_sample(
                topic=self.remote.evt_softwareVersions, cscVersion=watcher.__version__, subsystemVersions=""
            )

            await salobj.set_summary_state(self.remote, salobj.State.ENABLED, override="alarm_rule.yaml")
            assert len(self.csc.alarm_rules_info) == 2
            assert self.csc.alarm_rules_info[1].classname == "Enabled"
            assert self.csc.alarm_rules_info[2].classname == "Heartbeat"

    async def test_default_config_dir(self):
        async with self.make_csc(config_dir=None, initial_state=salobj.State.STANDBY):
            desired_config_pkg_name = "ts_config_ocs"
            desired_config_env_name = desired_config_pkg_name.upper() + "_DIR"
            desird_config_pkg_dir = os.environ[desired_config_env_name]
            desired_config_dir = pathlib.Path(desird_config_pkg_dir) / "Watcher/v6"
            assert self.csc.get_config_pkg() == desired_config_pkg_name
            assert self.csc.config_dir == desired_config_dir

    async def test_configuration_invalid(self):
        async with self.make_csc(config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY):
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
            await self.remote.cmd_start.set_start(configurationOverride="basic.yaml", timeout=STD_TIMEOUT)

    async def test_standard_state_transitions(self):
        async with self.make_csc(config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY):
            await self.check_standard_state_transitions(
                enabled_commands=(
                    "acknowledge",
                    "mute",
                    "showAlarms",
                    "unacknowledge",
                    "unmute",
                    "makeLogEntry",
                ),
                override="two_scriptqueue_enabled.yaml",
            )

    async def test_escalation_success(self):
        await self.check_escalation()

    async def test_escalation_service_down(self):
        await self.check_escalation(service_down=True)

    async def test_escalation_trigger_fails(self):
        await self.check_escalation(trigger_fails=True)

    async def test_escalation_resolve_fails(self):
        await self.check_escalation(resolve_fails=True)

    async def check_escalation(self, service_down=False, trigger_fails=False, resolve_fails=False):
        """Check escalation fields in the alarm event.

        Run the watcher with two TriggeredSeverity rules,
        as specified by "critical,yaml", one with escalation, one without.

        Parameters
        ----------
        service_down : `bool`
            Simulate the SquadCast service being down.
        trigger_fails : `bool`
            Simulate the SquadCast service rejecting the trigger attempt.
        resolve_fails : `bool`
            Simulate the SquadCast service rejecting the resolve attempt.
            This should still work, just log a warning.
        """
        if service_down and trigger_fails:
            raise ValueError("Cannot set both service_down and trigger_fails")
        escalation_fails = service_down or trigger_fails
        escalation_key = "anything"
        service_down_port = 80

        with utils.modify_environ(ESCALATION_KEY=escalation_key):
            async with (
                watcher.MockSquadCast(port=8080) as mock_server,
                self.make_csc(config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY),
                salobj.Controller(name="ATCamera", write_only=True) as atcamera,
            ):
                temp_critical_yaml_file = tempfile.NamedTemporaryFile(dir=TEST_CONFIG_DIR)
                with (
                    open(temp_critical_yaml_file.name, "w") as t,
                    open(TEST_CONFIG_DIR / "critical.yaml", "r") as c,
                ):
                    lines = c.readlines()
                    if service_down:
                        lines[-1] = f"escalation_url: http://127.0.0.1:{service_down_port}"
                    else:
                        lines[-1] = f"escalation_url: http://127.0.0.1:{mock_server.port}"
                    t.writelines(lines)

                atcamera_heartbeat_task = asyncio.create_task(self._publish_heart_beat(atcamera))

                await salobj.set_summary_state(
                    self.remote, state=salobj.State.ENABLED, override=temp_critical_yaml_file.name
                )

                # Test the escalation URL set from the copied critical.yaml.
                if service_down:
                    assert self.csc.escalation_endpoint_url == (
                        f"http://127.0.0.1:{service_down_port}/v2/incidents/api/{escalation_key}"
                    )
                else:
                    assert self.csc.escalation_endpoint_url == (
                        f"http://127.0.0.1:{mock_server.port}/v2/incidents/api/{escalation_key}"
                    )
                assert self.csc.config.escalation_url == self.csc.escalation_endpoint_url

                if trigger_fails:
                    mock_server.reject_next_request = True

                alarm_name1 = "Heartbeat.ATDome:0"
                alarm_name2 = "Heartbeat.ATCamera:0"
                known_alarms = [alarm_info.name for alarm_info in self.csc.alarms_info.values()]
                assert known_alarms == [alarm_name1, alarm_name2]

                # Alarm 1 will be escalated because it has an escalation
                # responder and the escalation delay is > 0.
                alarm_info1 = self.csc.alarms_info[alarm_name1]
                assert alarm_info1.escalate_to != ""

                expected_escalate_to_alarm1 = "stella"

                # Alarm 2 will never be escalated because it has no
                # escalation responder and the escalation delay is 0.
                alarm_info2 = self.csc.alarms_info[alarm_name2]
                assert alarm_info2.escalate_to == ""

                await self.check_all_alarms_events_are_none()

                alarm_name = ""
                while alarm_name != alarm_name1:
                    data = await self.assert_next_alarm()
                    alarm_name = data.name
                assert data.name == alarm_name1
                assert data.severity == AlarmSeverity.CRITICAL
                assert data.maxSeverity == AlarmSeverity.CRITICAL
                assert data.escalatedId == ""
                assert data.escalateTo == expected_escalate_to_alarm1

                assert data.timestampEscalate > 0
                timestamp_escalate = data.timestampEscalate

                data = await self.assert_next_alarm(
                    name=alarm_name1,
                    severity=AlarmSeverity.CRITICAL,
                    maxSeverity=AlarmSeverity.CRITICAL,
                    escalateTo=expected_escalate_to_alarm1,
                    timestampEscalate=timestamp_escalate,
                )
                assert alarm_info1.escalated_id != ""
                assert data.escalatedId == alarm_info1.escalated_id
                if escalation_fails:
                    assert alarm_info1.escalated_id.startswith("Failed: ")
                else:
                    assert not alarm_info1.escalated_id.startswith("Failed: ")
                if escalation_fails:
                    assert len(mock_server.incidents) == 0
                else:
                    assert len(mock_server.incidents) == 1
                    incident = mock_server.incidents[alarm_info1.escalated_id]
                    assert incident["event_id"] == alarm_info1.escalated_id
                    assert incident["status"] == "trigger"
                    assert "ATDome" in incident["message"]
                    assert "ATDome" in incident["tags"]["alarm_name"]
                    assert alarm_info1.escalate_to == incident["tags"]["responder"]
                    saved_incident_id = alarm_info1.escalated_id

                # Run the configured sequence of severities for alarm 2.
                atcamera_heartbeat_task.cancel()
                await self.assert_next_alarm(
                    name=alarm_name2,
                    severity=AlarmSeverity.CRITICAL,
                    maxSeverity=AlarmSeverity.CRITICAL,
                    escalatedId="",
                    escalateTo="",
                    timestampEscalate=0,
                )

                # Acknowledge alarm 1. That should make the alarm
                # be de-escalated (even though the alarm severity
                # is not back to NONE).
                if resolve_fails:
                    mock_server.reject_next_request = True
                await self.remote.cmd_acknowledge.set_start(
                    name=alarm_name1,
                    severity=AlarmSeverity.CRITICAL,
                    acknowledgedBy="arbitrary",
                )
                await self.assert_next_alarm(
                    name=alarm_name1,
                    severity=AlarmSeverity.CRITICAL,
                    maxSeverity=AlarmSeverity.CRITICAL,
                    escalatedId="",
                    escalateTo=expected_escalate_to_alarm1,
                    timestampEscalate=0,
                )
                # The escalated ID should have been cleared
                # (even if de-escalation fails),
                # so use the saved incident ID to access the incident.
                assert alarm_info1.escalated_id == ""
                if not escalation_fails:
                    assert len(mock_server.incidents) == 1
                    incident = mock_server.incidents[saved_incident_id]
                    assert incident["event_id"] == saved_incident_id
                    assert incident["status"] == "trigger" if resolve_fails else "resolve"
                    assert "ATDome" in incident["message"]
                    assert "ATDome" in incident["tags"]["alarm_name"]
                    assert alarm_info1.escalate_to == incident["tags"]["responder"]

    async def test_operation(self):
        """Run the watcher with a few rules and one disabled SAL component."""
        async with (
            self.make_csc(config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY),
            salobj.Controller(name="ATDome", write_only=True) as atdome,
        ):
            await salobj.set_summary_state(self.remote, state=salobj.State.ENABLED, override="enabled.yaml")

            atdome_alarm_name = "Enabled.ATDome:0"
            scriptqueue_alarm_name = "Enabled.ScriptQueue:2"

            # Check that disabled_sal_components eliminated a rule.
            assert len(self.csc.alarms_info) == 2
            assert list(self.csc.alarms_info.keys()) == [
                atdome_alarm_name,
                scriptqueue_alarm_name,
            ]

            await self.check_all_alarms_events_are_none()

            # Set various summary states for ATDome and check
            # the resulting alarms.
            await atdome.evt_summaryState.set_write(summaryState=salobj.State.DISABLED, force_output=True)
            await self.assert_next_alarm(
                name=atdome_alarm_name,
                severity=AlarmSeverity.WARNING,
                maxSeverity=AlarmSeverity.WARNING,
                acknowledged=False,
                acknowledgedBy="",
            )

            await atdome.evt_summaryState.set_write(summaryState=salobj.State.FAULT, force_output=True)
            await self.assert_next_alarm(
                name=atdome_alarm_name,
                severity=AlarmSeverity.CRITICAL,
                maxSeverity=AlarmSeverity.CRITICAL,
                acknowledged=False,
                acknowledgedBy="",
            )

            user = "test_operation"
            await self.remote.cmd_acknowledge.set_start(
                name=atdome_alarm_name,
                severity=AlarmSeverity.CRITICAL,
                acknowledgedBy=user,
            )
            await self.assert_next_alarm(
                name=atdome_alarm_name,
                severity=AlarmSeverity.CRITICAL,
                maxSeverity=AlarmSeverity.CRITICAL,
                acknowledged=True,
                acknowledgedBy=user,
            )

            # Set the state to ENABLED; this should reset the alarm.
            await atdome.evt_summaryState.set_write(summaryState=salobj.State.ENABLED, force_output=True)
            await self.assert_next_alarm(
                name=atdome_alarm_name,
                severity=AlarmSeverity.NONE,
                maxSeverity=AlarmSeverity.NONE,
                acknowledged=False,
                acknowledgedBy="",
            )

            # Go all the way to standby and back. Alarms should still work.
            await salobj.set_summary_state(remote=self.remote, state=salobj.State.STANDBY)
            assert len(self.csc.alarm_rules_info) == 0
            assert len(self.csc.alarms_info) == 0

            await salobj.set_summary_state(
                remote=self.remote, state=salobj.State.ENABLED, override="enabled.yaml"
            )

            await self.check_all_alarms_events_are_none()

            await atdome.evt_summaryState.set_write(summaryState=salobj.State.DISABLED, force_output=True)
            await self.assert_next_alarm(
                name=atdome_alarm_name,
                severity=AlarmSeverity.WARNING,
                maxSeverity=AlarmSeverity.WARNING,
                acknowledged=False,
                acknowledgedBy="",
            )

    async def test_ess_operation_after_standby(self):
        async with (
            self.make_csc(config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY),
            salobj.Controller(name="ESS", index=1, write_only=True) as ess_1,
        ):
            await salobj.set_summary_state(
                self.remote,
                state=salobj.State.ENABLED,
                override="over_temperature.yaml",
            )

            over_temperature_alarm_name = "OverTemperature.TestOverTemperature"
            assert list(self.csc.alarms_info.keys()) == [over_temperature_alarm_name]
            assert len(self.csc.alarm_rules_info) == 1
            assert 1 in self.csc.alarm_rules_info.keys()
            config_for_alarm_rule = self.csc.alarm_rules_info[1].config
            alarm_configs = config_for_alarm_rule.rules[0]["configs"]
            assert len(alarm_configs) == 1
            alarm_config = alarm_configs[0]
            warning_level = alarm_config["warning_level"]
            assert len(alarm_config["temperature_sensors"]) == 1
            assert alarm_config["temperature_sensors"][0]["sal_index"] == 1
            assert len(alarm_config["temperature_sensors"][0]["sensor_info"]) == 1
            sensor_name = alarm_config["temperature_sensors"][0]["sensor_info"][0]["sensor_name"]
            ess_1.tel_temperature.set(sensorName=sensor_name, numChannels=1, location="some location")

            async def send_temperature_data(temperature):
                ess_1.tel_temperature.data.temperatureItem[0] = temperature
                await ess_1.tel_temperature.write()

            await self.check_all_alarms_events_are_none()

            await send_temperature_data(warning_level + 1)

            await self.assert_next_alarm(
                name=over_temperature_alarm_name,
                severity=AlarmSeverity.WARNING,
                maxSeverity=AlarmSeverity.WARNING,
                acknowledged=False,
                acknowledgedBy="",
                timeout=5,
            )

            await send_temperature_data(warning_level - 1)

            await self.assert_next_alarm(
                name=over_temperature_alarm_name,
                severity=AlarmSeverity.NONE,
                maxSeverity=AlarmSeverity.WARNING,
                acknowledged=False,
                acknowledgedBy="",
                timeout=5,
            )

            # Send CSC to standby and enabled and try again.
            await salobj.set_summary_state(remote=self.remote, state=salobj.State.STANDBY)
            await salobj.set_summary_state(
                remote=self.remote,
                state=salobj.State.ENABLED,
                override="over_temperature.yaml",
            )

            await self.check_all_alarms_events_are_none()

            await send_temperature_data(warning_level + 1)

            await self.assert_next_alarm(
                name=over_temperature_alarm_name,
                severity=AlarmSeverity.WARNING,
                maxSeverity=AlarmSeverity.WARNING,
                acknowledged=False,
                acknowledgedBy="",
                timeout=5,
            )

    async def test_auto_acknowledge_unacknowledge(self):
        user = "chaos"
        async with (
            self.make_csc(config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY),
            salobj.Controller(name="ATDome", write_only=True) as atdome,
        ):
            await salobj.set_summary_state(
                self.remote,
                state=salobj.State.ENABLED,
                override="enabled_short_auto_delays.yaml",
            )

            # Check the values encoded in the yaml config file.
            expected_auto_acknowledge_delay = 0.51
            expected_auto_unacknowledge_delay = 0.52
            assert self.csc.config.auto_acknowledge_delay == pytest.approx(expected_auto_acknowledge_delay)
            assert self.csc.config.auto_unacknowledge_delay == pytest.approx(
                expected_auto_unacknowledge_delay
            )

            atdome_alarm_name = "Enabled.ATDome:0"

            await self.check_all_alarms_events_are_none()

            # Make the ATDome alarm stale.
            await atdome.evt_summaryState.set_write(summaryState=salobj.State.DISABLED, force_output=True)
            await self.assert_next_alarm(
                name=atdome_alarm_name,
                severity=AlarmSeverity.WARNING,
                maxSeverity=AlarmSeverity.WARNING,
                acknowledged=False,
                acknowledgedBy="",
            )

            await atdome.evt_summaryState.set_write(summaryState=salobj.State.ENABLED, force_output=True)
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
            await atdome.evt_summaryState.set_write(summaryState=salobj.State.DISABLED, force_output=True)
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
        async with (
            self.make_csc(config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY),
            salobj.Controller(name="ATDome", write_only=True) as atdome,
            salobj.Controller(name="ScriptQueue", index=2, write_only=True) as script_queue2,
            salobj.Controller(name="ATCamera", write_only=True) as atcamera,
        ):
            # Make sure CSCs are in ENABLED
            await atdome.evt_summaryState.set_write(summaryState=salobj.State.ENABLED)
            await atcamera.evt_summaryState.set_write(summaryState=salobj.State.ENABLED)
            await script_queue2.evt_summaryState.set_write(summaryState=salobj.State.ENABLED)

            await salobj.set_summary_state(self.remote, state=salobj.State.ENABLED, override="enabled.yaml")

            await self.check_all_alarms_events_are_none()

            atdome_alarm_name = "Enabled.ATDome:0"
            scriptqueue_alarm_name = "Enabled.ScriptQueue:2"

            # All alarms should be nominal, so showAlarms should output
            # no alarm events.
            for alarm_name in self.csc.alarms_info:
                alarm = self.csc.alarms_info[alarm_name]
                assert alarm.nominal
            await self.remote.cmd_showAlarms.start(timeout=STD_TIMEOUT)

            await self.check_all_alarms_events_are_none()

            # Fire the ATDome alarm.
            await atdome.evt_summaryState.set_write(summaryState=salobj.State.DISABLED, force_output=True)
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
            assert set(alarm_names) == {"Enabled.ATDome:0", "Enabled.ScriptQueue:2"}
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
            await atdome.evt_summaryState.set_write(summaryState=salobj.State.ENABLED, force_output=True)
            await self.assert_next_alarm(
                name=atdome_alarm_name,
                severity=AlarmSeverity.NONE,
                maxSeverity=AlarmSeverity.NONE,
                acknowledged=False,
                acknowledgedBy="",
            )

            # Send the showAlarms command again.
            await self.remote.cmd_showAlarms.start(timeout=STD_TIMEOUT)
            alarm_names = set()
            for index, alarm_name in enumerate(self.csc.alarms_info):
                alarm_names.add(alarm_name)
                data = await self.remote.evt_alarm.next(flush=False, timeout=STD_TIMEOUT)
                if data.name == scriptqueue_alarm_name:
                    expected_severity = AlarmSeverity.WARNING
                else:
                    expected_severity = AlarmSeverity.NONE
                assert data.severity == expected_severity
                assert data.maxSeverity == expected_severity
                assert not data.acknowledged
                assert data.acknowledgedBy == ""
            assert self.csc.alarms_info.keys() == alarm_names

    @patch("aiohttp.ClientSession.post")
    async def test_make_log_entry(self, mock_post):
        """Test the makeLogEntry command."""

        # Send the makeLogEntry command.
        async with (
            self.make_csc(config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY),
            salobj.Controller(name="ATDome", write_only=True) as atdome,
        ):
            atdome_alarm_name = "Enabled.ATDome:0"

            await atdome.evt_summaryState.set_write(summaryState=salobj.State.ENABLED)
            await salobj.set_summary_state(self.remote, state=salobj.State.ENABLED, override="enabled.yaml")
            await self.check_all_alarms_events_are_none()

            await atdome.evt_summaryState.set_write(summaryState=salobj.State.FAULT, force_output=True)
            await self.assert_next_alarm(
                name=atdome_alarm_name,
                severity=AlarmSeverity.CRITICAL,
                maxSeverity=AlarmSeverity.CRITICAL,
                acknowledged=False,
                acknowledgedBy="",
            )

            test_case_json = {"key": "TEST-123", "status": "PASS"}
            mock_response = AsyncMock()
            mock_response.json.return_value = test_case_json
            mock_post.return_value.__aenter__.return_value = mock_response

            await self.remote.cmd_makeLogEntry.set_start(
                name=atdome_alarm_name,
                timeout=STD_TIMEOUT,
            )

            post_args = mock_post.call_args.kwargs
            assert post_args["url"] == "https://fake.url.com/narrativelog/messages"
            assert post_args["json"]["message_text"] == "alarm:Enabled.ATDome:0 severity=4 FAULT state"
            # The POST response contains three additional keys
            # (user_id, date_begin, date_end) that will vary from
            # test to test.  The are removed from this expected value
            # and the mock_post.call_args dict.
            expected = {
                "url": "https://fake.url.com/narrativelog/messages",
                "json": {
                    "message_text": "alarm:Enabled.ATDome:0 severity=4 FAULT state",
                    "level": 50,
                    "user_agent": "Watcher",
                    "is_human": False,
                    "tags": ["watcher", "alarm", "make_log_entry"],
                },
            }
            self.assertIn("user_id", post_args["json"])
            self.assertIn("date_begin", post_args["json"])
            self.assertIn("date_end", post_args["json"])
            del post_args["json"]["user_id"]
            del post_args["json"]["date_begin"]
            del post_args["json"]["date_end"]
            self.assertEqual(post_args, expected)

    async def test_mute(self):
        """Test the mute and unmute command."""
        async with (
            self.make_csc(config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY),
            salobj.Controller(name="ATDome", write_only=True) as atdome,
            salobj.Controller(name="ATCamera", write_only=True) as atcamera,
            salobj.Controller(name="ScriptQueue", index=2, write_only=True) as atqueue,
        ):
            # Make sure CSCs are in ENABLED
            await atdome.evt_summaryState.set_write(summaryState=salobj.State.ENABLED)
            await atcamera.evt_summaryState.set_write(summaryState=salobj.State.ENABLED)
            await atqueue.evt_summaryState.set_write(summaryState=salobj.State.ENABLED)

            await salobj.set_summary_state(self.remote, state=salobj.State.ENABLED, override="enabled.yaml")
            nrules = len(self.csc.alarms_info)

            # All rules should be nominal.
            await self.check_all_alarms_events_are_none()

            user1 = "test_mute 1"
            # Mute all alarms for a short time,
            # then wait for them to unmute themselves.
            logging.info(f"test_mute: Muting {nrules} alarms.")
            await self.remote.cmd_mute.set_start(
                name="Enabled.*",
                duration=0.5,
                severity=AlarmSeverity.SERIOUS,
                mutedBy=user1,
                timeout=STD_TIMEOUT,
            )

            logging.info(f"test_mute: Waiting for {nrules} muted alarm events.")
            # The first batch of alarm events should be for the muted alarms.
            muted_names = set()
            while len(muted_names) < nrules:
                data = await self.assert_next_alarm(mutedSeverity=AlarmSeverity.SERIOUS, mutedBy=user1)
                if data.name in muted_names:
                    raise self.fail(f"Duplicate alarm event for muting {data.name}")
                muted_names.add(data.name)
                logging.info(f"test_mute: Muted alarm event: {data.name}")

            logging.info(f"test_mute: Waiting for {nrules} unmuted alarms.")
            # The next batch of alarm events should be for the unmuted alarms.
            unmuted_names = set()
            while len(unmuted_names) < nrules:
                data = await self.assert_next_alarm(mutedSeverity=AlarmSeverity.NONE, mutedBy="")
                if data.name in unmuted_names:
                    raise self.fail(f"Duplicate alarm event for auto-unmuting {data.name}")
                unmuted_names.add(data.name)
                logging.info(f"test_mute: Unmuted alarm event: {data.name}")

            # Now mute one rule for a long time, then explicitly unmute it.
            user2 = "test_mute 2"
            full_name = "Enabled.ScriptQueue:2"
            logging.info(f"test_mute: Muting {full_name}.")
            assert full_name in self.csc.alarms_info
            await self.remote.cmd_mute.set_start(
                name=full_name,
                duration=5,
                severity=AlarmSeverity.SERIOUS,
                mutedBy=user2,
                timeout=STD_TIMEOUT,
            )
            await self.assert_next_alarm(name=full_name, mutedSeverity=AlarmSeverity.SERIOUS, mutedBy=user2)
            # There should be the only alarm event from the mute command.
            with pytest.raises(asyncio.TimeoutError):
                await self.remote.evt_alarm.next(flush=False, timeout=NODATA_TIMEOUT)

            logging.info(f"test_mute: Unmuting {full_name}.")
            await self.remote.cmd_unmute.set_start(name=full_name, timeout=STD_TIMEOUT)
            await self.assert_next_alarm(name=full_name, mutedSeverity=AlarmSeverity.NONE, mutedBy="")
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
        async with (
            self.make_csc(config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY),
            salobj.Controller(name="ScriptQueue", index=0, write_only=True) as script_queue,
        ):
            # Make sure both queues are in ENABLED.
            await script_queue.evt_summaryState.set_write(
                summaryState=salobj.State.ENABLED, salIndex=1, force_output=True
            )
            await script_queue.evt_summaryState.set_write(
                summaryState=salobj.State.ENABLED, salIndex=2, force_output=True
            )

            await salobj.set_summary_state(
                self.remote,
                state=salobj.State.ENABLED,
                override="two_scriptqueue_enabled.yaml",
            )

            alarm_name1 = "Enabled.ScriptQueue:1"
            alarm_name2 = "Enabled.ScriptQueue:2"
            assert len(self.csc.alarms_info) == 2
            assert list(self.csc.alarms_info.keys()) == [alarm_name1, alarm_name2]

            await self.check_all_alarms_events_are_none()

            # Send alarm 1 to severity warning.
            await script_queue.evt_summaryState.set_write(
                summaryState=salobj.State.DISABLED, salIndex=1, force_output=True
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
            self.remote.evt_alarm.flush()
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
            await script_queue.evt_summaryState.set_write(
                summaryState=salobj.State.ENABLED, salIndex=1, force_output=True
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

    async def test_set_log_level(self):
        async with (
            self.make_csc(config_dir=TEST_CONFIG_DIR, initial_state=salobj.State.STANDBY),
            salobj.Controller(name="ATDome", write_only=True) as atdome,
            salobj.Controller(name="ATCamera", write_only=True) as atcamera,
            salobj.Controller(name="ScriptQueue", index=2, write_only=True) as atqueue,
        ):
            # Make sure CSCs are in ENABLED
            await atdome.evt_summaryState.set_write(summaryState=salobj.State.ENABLED)
            await atcamera.evt_summaryState.set_write(summaryState=salobj.State.ENABLED)
            await atqueue.evt_summaryState.set_write(summaryState=salobj.State.ENABLED)

            self.log_levels: dict[int, int] = {}
            self.csc.evt_logLevel_callback = self.evt_logLevel_callback

            await salobj.set_summary_state(self.remote, state=salobj.State.ENABLED, override="enabled.yaml")
            nrules = len(self.csc.alarm_rules_info)

            # All rules should be nominal.
            await self.check_all_alarms_events_are_none()

            # Set the log level to DEBUG.
            await self.remote.cmd_setLogLevel.set_start(level=logging.DEBUG)
            self.csc.log.info("Waiting for log level to be set")
            while self.csc.log.level != logging.DEBUG:
                await asyncio.sleep(0.1)

            while len(self.log_levels) < nrules:
                await asyncio.sleep(STD_TIMEOUT)

    async def evt_logLevel_callback(self, data):
        """Handle logLevel event from the alarm subprocess."""
        self.csc.log.info(f"Received logLevel event for {data.salIndex=} with {data.level=}")
        self.log_levels[data.salIndex] = data.level

    async def _publish_heart_beat(self, controller):
        while True:
            await controller.evt_heartbeat.write()
            await asyncio.sleep(0.25)
