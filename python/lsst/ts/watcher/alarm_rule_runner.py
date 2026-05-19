from __future__ import annotations

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

__all__ = ["AlarmRuleRunner", "UnexpectedAlarmRuleStateError"]

import asyncio
import contextlib
import types
import typing

import yaml

from lsst.ts import salobj, utils
from lsst.ts.salobj import type_hints
from lsst.ts.xml.enums.AlarmRule import AlarmRuleState

from .model import Model

MINIMAL_WAIT = 0.001  # seconds
RUN_TASK_WAIT = 0.1  # seconds
TASK_CANCEL_WAIT_TIME = 0.1  # seconds
MAX_TASK_CANCEL_WAIT_TIME = 5.0  # seconds
HEARTBEAT_INTERVAL = 5.0  # seconds


class UnexpectedAlarmRuleStateError(Exception):
    pass


class AlarmRuleRunner(salobj.Controller):
    def __init__(self, rule_name: str, index: int):
        super().__init__(name="AlarmRule", index=index)

        self.rule_name = rule_name
        self.model: Model | None = None

        self._run_task: asyncio.Future = utils.make_done_future()
        self._heartbeat_task: asyncio.Future = utils.make_done_future()

        self._should_be_running: asyncio.Future = utils.make_done_future()
        self._should_produce_heartbeats = False

        self.state = AlarmRuleState.UNCONFIGURED

    async def _heartbeat_loop(self) -> None:
        """Output heartbeat at regular intervals."""
        while self._should_produce_heartbeats:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                await self.evt_heartbeat.write()
            except asyncio.CancelledError:
                self._should_produce_heartbeats = False
            except Exception:
                self.log.exception("Heartbeat output failed.")
                self._should_produce_heartbeats = False

    async def _wait_for_task_done(self, task: asyncio.Future) -> None:
        """Wait for the task to finish running.

        Wait for at most `MAX_TASK_CANCEL_WAIT_TIME` seconds before canceling
        the task. This doesn't check if the task already was canceled or if
        there was an error in the task.

        Parameters
        ----------
        task : `asyncio.Future`
            The task to wait for.
        """
        if not task.done():
            self.log.debug(f"Waiting for task {task} to be done.")
            done_wait_start = utils.current_tai()
            while not task.done():
                await asyncio.sleep(TASK_CANCEL_WAIT_TIME)
                now = utils.current_tai()
                if now - done_wait_start > MAX_TASK_CANCEL_WAIT_TIME:
                    task.cancel()

    async def _set_state(self, state: AlarmRuleState) -> None:
        self.state = state
        await self.evt_state.set_write(alarmName=self.rule_name, state=state.value)

    async def start(self) -> None:
        """Finish construction and start running the alarm rule."""
        await super().start()

        await self._wait_for_task_done(self._heartbeat_task)
        self._should_produce_heartbeats = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _run(self) -> None:
        """Run the alarm rule."""
        await self._set_state(AlarmRuleState.RUNNING)
        self._should_be_running = asyncio.Future()
        await self.model.enable()
        await self._should_be_running

    async def close_tasks(self) -> None:
        """Close all tasks."""
        if not self._should_be_running.done():
            self._should_be_running.set_result(None)

        if self.model is not None:
            self.model.disable()
            await self.model.close()
            self.model = None

        await self._wait_for_task_done(self._run_task)
        await self._wait_for_task_done(self._heartbeat_task)

    @contextlib.asynccontextmanager
    async def _stopping(self) -> typing.AsyncGenerator[None, None]:
        await self._set_state(AlarmRuleState.STOPPING)
        yield
        await self._set_state(AlarmRuleState.STOPPED)

    async def _stop(self) -> None:
        """Stop the alarm rule and all tasks."""
        async with self._stopping():
            await self.close_tasks()
        asyncio.create_task(self.close())

    async def do_configure(self, data: type_hints.BaseMsgType) -> None:
        """Configure the currently loaded alarm rule.

        Parameters
        ----------
        data : ``cmd_configure.DataType``
            Configuration.

        Raises
        ------
        salobj.ExpectedError
            If ``self.state.state`` is not
            `lsst.ts.xml.enums.AlarmRule.AlarmRuleState.UNCONFIGURED`.
        """
        self.log.debug("do_configure")

        expected_state = AlarmRuleState.UNCONFIGURED
        if self.state != expected_state:
            raise UnexpectedAlarmRuleStateError(
                f"Invalid AlarmRule state {self.state.name}; expected {expected_state.name}."
            )

        config_yaml: str = data.config

        try:
            config_dict_from_yaml = yaml.safe_load(config_yaml)
            config = types.SimpleNamespace(**config_dict_from_yaml)
            # Only keep the rule for which this AlarmRuleRunner was created.
            config.rules = [rule for rule in config.rules if rule["classname"] == self.rule_name]
            self.model = Model(
                domain=self.domain,
                config=config,
                alarm_callback=self.output_alarm,
                log=self.log,
            )

            await self.model.start_task
        except Exception as e:
            errmsg = f"config({config_yaml}) failed"
            full_errmsg = f"{errmsg}: {e}"  # includes the exception
            self.log.exception(errmsg)
            await self._set_state(AlarmRuleState.CONFIGURE_FAILED)
            raise salobj.ExpectedError(full_errmsg) from e

        # Prepare and send the description event.
        remote_names = []
        for rule in self.model.rules.values():
            remote_info_list = rule.remote_info_list
            for remote_info in remote_info_list:
                remote_names.append(f"{remote_info.name}:{remote_info.index}")

        await self.evt_description.set_write(
            alarmName=self.rule_name,
            description=f"AlarmRule:{self.salinfo.index} for {self.rule_name}",
            remotes=",".join(remote_names),
        )

        await self._set_state(AlarmRuleState.CONFIGURED)
        await asyncio.sleep(MINIMAL_WAIT)

    @contextlib.asynccontextmanager
    async def _faling(self) -> typing.AsyncGenerator[None, None]:
        await self._set_state(AlarmRuleState.FAILING)
        yield
        await self._set_state(AlarmRuleState.FAILED)

    async def do_run(self, data: type_hints.BaseMsgType) -> None:
        """Run the alarm rule.

        The alarm rule must have been configured.

        Parameters
        ----------
        data : ``cmd_run.DataType``
            Ignored.

        Raises
        ------
        salobj.ExpectedError
            If ``self.state.state`` is not
            `lsst.ts.xml.enums.Script.AlarmRuleState.CONFIGURED`.
        """
        self.log.debug("do_run")

        expected_state = AlarmRuleState.CONFIGURED
        if self.state != expected_state:
            raise UnexpectedAlarmRuleStateError(
                f"Invalid AlarmRule state {self.state.name}; expected {expected_state.name}."
            )

        try:
            self._run_task = asyncio.create_task(self._run())
            await self._run_task
        except asyncio.CancelledError:
            # Deliberately ignore.
            pass
        except BaseException as e:
            if not isinstance(e, salobj.ExpectedError):
                self.log.exception("Error in run.")
            async with self._faling():
                await self.close_tasks()
        finally:
            if self.state != AlarmRuleState.FAILED:
                await self._stop()

    async def do_stop(self, data: type_hints.BaseMsgType) -> None:
        """Stop the alarm rule.

        Parameters
        ----------
        data : ``cmd_stop.DataType``
            Ignored.

        Notes
        -----
        This is usually called when the Watcher goes to DISABLED state.
        """
        self.log.debug("do_stop")

        await self._stop()

    async def do_mute(self, data: type_hints.BaseMsgType) -> None:
        """Mute the alarm of this rule.

        Parameters
        ----------
        data : ``cmd_mute.DataType``
            The data for the mute command.
        """
        await self.model.mute_alarm(
            name=data.alarmName, duration=data.duration, severity=data.severity, user=data.mutedBy
        )

    async def do_unmute(self, data: type_hints.BaseMsgType) -> None:
        """Unmute the alarm of this rule.

        Parameters
        ----------
        data : ``cmd_unmute.DataType``
            The data for the unmute command.
        """
        await self.model.unmute_alarm(name=data.alarmName)

    async def do_acknowledge(self, data: type_hints.BaseMsgType) -> None:
        """Acknowledge the alarm of this rule.

        Parameters
        ----------
        data : ``cmd_acknowledge.DataType``
            The data for the acknowledge command.
        """
        self.log.debug(f"do_acknowledge {data.alarmName=}, {data.severity=}, {data.acknowledgedBy=}")
        await self.model.acknowledge_alarm(
            name=data.alarmName, severity=data.severity, user=data.acknowledgedBy
        )

    async def do_unacknowledge(self, data: type_hints.BaseMsgType) -> None:
        """Unacknowledge the alarm of this rule.

        Parameters
        ----------
        data : ``cmd_unacknowledge.DataType``
            The data for the unacknowledge command.
        """
        self.log.debug(f"do_unacknowledge {data.alarmName=}")
        await self.model.unacknowledge_alarm(name=data.alarmName)

    async def output_alarm(self, alarm):
        """Output the alarm event for one alarm."""
        self.log.debug(
            f"Outputting alarm with {alarm.name=}, {alarm.severity=}, {alarm.reason=}, "
            f"{alarm.acknowledged=}, {alarm.muted=}"
        )
        await self.evt_alarm.set_write(
            alarmName=alarm.name,
            severity=alarm.severity,
            reason=alarm.reason,
            maxSeverity=alarm.max_severity,
            acknowledged=alarm.acknowledged,
            acknowledgedBy=alarm.acknowledged_by,
            mutedSeverity=alarm.muted_severity,
            mutedBy=alarm.muted_by,
            escalateTo=alarm.escalation_responder,
            escalatedId=alarm.escalated_id,
            timestampSeverityOldest=alarm.timestamp_severity_oldest,
            timestampMaxSeverity=alarm.timestamp_max_severity,
            timestampAcknowledged=alarm.timestamp_acknowledged,
            timestampAutoAcknowledge=alarm.timestamp_auto_acknowledge,
            timestampAutoUnacknowledge=alarm.timestamp_auto_unacknowledge,
            timestampEscalate=alarm.timestamp_escalate,
            timestampUnmute=alarm.timestamp_unmute,
            force_output=True,
        )

    @classmethod
    def make_from_cmd_line(cls, **kwargs: typing.Any) -> AlarmRuleRunner | None:
        raise NotImplementedError()

    @classmethod
    async def amain(cls, **kwargs: typing.Any) -> None:
        raise NotImplementedError()
