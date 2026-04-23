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
import pathlib
import unittest
from collections.abc import AsyncGenerator

from lsst.ts import salobj, utils, watcher
from lsst.ts.xml.enums.AlarmRule import AlarmRuleState
from lsst.ts.xml.enums.Watcher import AlarmSeverity

# Timeout for normal operations (seconds)
STD_TIMEOUT = 5
# Minimal wait time (seconds).
MINIMAL_WAIT = 0.001


class AlarmRuleRunnerTestCase(unittest.IsolatedAsyncioTestCase):
    _index_iter = utils.index_generator()

    def read_config_file(self, path):
        with open(path, "r") as f:
            return f.read()

    def setUp(self) -> None:
        salobj.set_test_topic_subname(randomize=True)

    async def asyncTearDown(self) -> None:
        """Runs after each test is completed."""
        await salobj.delete_kafka_topics()

    @contextlib.asynccontextmanager
    async def make_component_and_remote(self) -> AsyncGenerator[None, None]:
        index = next(self._index_iter)
        configpath = pathlib.Path(__file__).resolve().parent / "data" / "config" / "csc"

        async with (
            watcher.AlarmRuleRunner(rule_name="Heartbeat", index=index) as self.rule_runner,
            salobj.Remote(
                domain=self.rule_runner.domain, name="AlarmRule", index=index
            ) as self.rule_runner_remote,
        ):
            # Prepare the configuraration and other data.
            self.config_data = self.rule_runner.cmd_configure.DataType()
            self.config_data.config = self.read_config_file(configpath / "alarm_rule.yaml")
            self.run_data = self.rule_runner.cmd_run.DataType()
            self.stop_data = self.rule_runner.cmd_stop.DataType()
            self.mute_data = self.rule_runner.cmd_mute.DataType()
            self.unmute_data = self.rule_runner.cmd_unmute.DataType()
            self.acknowledge_data = self.rule_runner.cmd_acknowledge.DataType()
            self.unacknowledge_data = self.rule_runner.cmd_unacknowledge.DataType()

            # Keep track of raised alarms.
            self.raised_alarms: set[str] = set()

            yield

    async def test_life_cycle(self):
        async with self.make_component_and_remote():
            # Validate start up.
            assert self.rule_runner.salinfo is not None
            assert not self.rule_runner._heartbeat_task.done()
            assert self.rule_runner._run_task.done()
            assert self.rule_runner.state == AlarmRuleState.UNCONFIGURED
            assert self.rule_runner.model is None
            async with asyncio.timeout(STD_TIMEOUT):
                await self.rule_runner_remote.evt_heartbeat.next(flush=True)

            # Execute and validate do_configure.
            await self.rule_runner.do_configure(self.config_data)
            await asyncio.sleep(MINIMAL_WAIT)
            async with asyncio.timeout(STD_TIMEOUT):
                data = await self.rule_runner_remote.evt_state.next(flush=False)
                assert data.state == AlarmRuleState.CONFIGURED.value
            async with asyncio.timeout(STD_TIMEOUT):
                await self.rule_runner_remote.evt_description.next(flush=False)
            assert self.rule_runner._run_task.done()
            assert self.rule_runner.model is not None
            assert len(self.rule_runner.model.rules) == 2

            # Execute and validate do_run.
            run_task = asyncio.create_task(self.rule_runner.do_run(self.run_data))
            await asyncio.sleep(MINIMAL_WAIT)
            async with asyncio.timeout(STD_TIMEOUT):
                data = await self.rule_runner_remote.evt_state.next(flush=False)
                assert data.state == AlarmRuleState.RUNNING.value
            assert not self.rule_runner._run_task.done()

            # Execute and validate do_stop.
            await self.rule_runner.do_stop(self.stop_data)
            await asyncio.sleep(MINIMAL_WAIT)
            async with asyncio.timeout(STD_TIMEOUT):
                data = await self.rule_runner_remote.evt_state.next(flush=False)
                assert data.state == AlarmRuleState.STOPPING.value
            async with asyncio.timeout(STD_TIMEOUT):
                data = await self.rule_runner_remote.evt_state.next(flush=False)
                assert data.state == AlarmRuleState.STOPPED.value

            # Validate clean up.
            while not run_task.done():
                await asyncio.sleep(MINIMAL_WAIT)
            assert self.rule_runner._heartbeat_task.done()
            assert self.rule_runner._run_task.done()
            assert self.rule_runner.model is None

    async def validate_alarm_event(
        self,
        expected_severity: AlarmSeverity,
        expected_reason: str | None = None,
        expected_acknowledged: bool | None = None,
        expected_muted: bool | None = None,
    ) -> None:
        data = await self.rule_runner_remote.evt_alarm.next(flush=False)
        assert data.severity == expected_severity.value
        if expected_reason:
            assert data.reason == expected_reason
        if expected_acknowledged:
            assert data.acknowledged is expected_acknowledged
        if expected_muted:
            assert data.mutedSeverity == data.severity
        if data.severity == AlarmSeverity.NONE.value and data.alarmName in self.raised_alarms:
            self.raised_alarms.remove(data.alarmName)
        elif data.severity != AlarmSeverity.NONE.value and data.alarmName not in self.raised_alarms:
            self.raised_alarms.add(data.alarmName)

    async def validate_first_second_alarm_event(self):
        # The first alarm event always is sent at start up and no alarm was
        # raised yet. Since the config is for two Remotes, the event is
        # emitted twice, once for each Remote.
        await self.validate_alarm_event(
            expected_severity=AlarmSeverity.NONE,
            expected_reason="",
            expected_acknowledged=False,
            expected_muted=False,
        )
        await self.validate_alarm_event(
            expected_severity=AlarmSeverity.NONE,
            expected_reason="",
            expected_acknowledged=False,
            expected_muted=False,
        )

        # The next alarm event indicates an alarm.
        await self.validate_alarm_event(
            expected_severity=AlarmSeverity.CRITICAL,
            expected_reason="Heartbeat event not seen in 1 seconds",
            expected_acknowledged=False,
            expected_muted=False,
        )

    async def test_alarm(self):
        async with self.make_component_and_remote():
            await self.rule_runner.do_configure(self.config_data)
            asyncio.create_task(self.rule_runner.do_run(self.run_data))

            # Make sure that an alarm is raised.
            await self.validate_first_second_alarm_event()

            # Make sure all remotes send a heartbeat.
            for rule in self.rule_runner.model.rules.values():
                for remote_info in rule.remote_info_list:
                    async with salobj.Controller(
                        name=remote_info.name, index=remote_info.index
                    ) as controller:
                        await controller.evt_heartbeat.write()
                        await asyncio.sleep(MINIMAL_WAIT)

            # Validate that the alarm no longer is raised.
            await self.validate_alarm_event(expected_severity=AlarmSeverity.NONE)

            await self.rule_runner.do_stop(self.stop_data)

    async def test_ack_unack_alarm(self):
        async with self.make_component_and_remote():
            await self.rule_runner.do_configure(self.config_data)

            # For some reason the alarms need to be reset here when running
            # other tests that acknowledge alarms (heartbeat rule test for
            # example). Resetting at the end of those tests doesn't work.
            for rule in self.rule_runner.model.rules:
                self.rule_runner.model.rules[rule].alarm.reset()

            asyncio.create_task(self.rule_runner.do_run(self.run_data))

            # Make sure that an alarm is raised.
            await self.validate_first_second_alarm_event()

            # Prepare the data for each command.
            raised_alarm = next(iter(self.raised_alarms))
            for data in [self.acknowledge_data, self.unacknowledge_data]:
                data.alarmName = raised_alarm
                data.severity = AlarmSeverity.CRITICAL.value
                data.acknowledgedBy = "Unit Test"

            # Acknowledge the alarm.
            await self.rule_runner.do_acknowledge(self.acknowledge_data)
            await self.validate_alarm_event(
                expected_severity=AlarmSeverity.CRITICAL, expected_acknowledged=True, expected_muted=False
            )

            # Unacknowledge the alarm.
            await self.rule_runner.do_unacknowledge(self.unacknowledge_data)
            await self.validate_alarm_event(
                expected_severity=AlarmSeverity.CRITICAL, expected_acknowledged=False, expected_muted=False
            )

            await self.rule_runner.do_stop(self.stop_data)

    async def test_mute_unmute_alarm(self):
        async with self.make_component_and_remote():
            await self.rule_runner.do_configure(self.config_data)
            asyncio.create_task(self.rule_runner.do_run(self.run_data))

            # Make sure that an alarm is raised.
            await self.validate_first_second_alarm_event()

            # Prepare the data for each command.
            raised_alarm = next(iter(self.raised_alarms))
            for data in [self.mute_data, self.unmute_data]:
                data.alarmName = raised_alarm
                data.severity = AlarmSeverity.CRITICAL.value
                data.duration = 18600
                data.mutedBy = "Unit Test"

            # Mute the alarm.
            await self.rule_runner.do_mute(self.mute_data)
            await self.validate_alarm_event(
                expected_severity=AlarmSeverity.CRITICAL, expected_acknowledged=False, expected_muted=True
            )

            # Unmute the alarm.
            await self.rule_runner.do_unmute(self.unmute_data)
            await self.validate_alarm_event(
                expected_severity=AlarmSeverity.CRITICAL, expected_acknowledged=False, expected_muted=False
            )

            await self.rule_runner.do_stop(self.stop_data)
