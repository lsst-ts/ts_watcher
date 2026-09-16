# This file is part of ts_watcher.
#
# Developed for the Vera C. Rubin Observatory Telescope and Site Systems.
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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

__all__ = ["AlarmRuleRunner", "UnexpectedAlarmRuleStateError", "run_alarm_rule_runner"]

import argparse
import asyncio
import contextlib
import sys
import types
import typing
import uuid
import warnings
from http import HTTPStatus

import aiohttp
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
ACK_IN_PROGRESS_WAIT_TIME = 5.0  # seconds


class UnexpectedAlarmRuleStateError(Exception):
    pass


class AlarmRuleRunner(salobj.Controller):
    def __init__(self, rule_name: str, index: int):
        self.http_client = aiohttp.ClientSession()

        # TODO OSW-2899 Remove backward compatibiliy with SalObj v8.2.9.
        try:
            super().__init__(
                name="AlarmRule", index=index, do_callbacks=True, discard_out_of_order_events=False
            )
        except TypeError:
            super().__init__(name="AlarmRule", index=index, do_callbacks=True)

        self.rule_name = rule_name
        self.model: Model | None = None

        self._run_task: asyncio.Future = utils.make_done_future()
        self._close_task: asyncio.Future = utils.make_done_future()
        self._heartbeat_task: asyncio.Future = utils.make_done_future()

        self._should_be_running: asyncio.Future = utils.make_done_future()
        self._should_produce_heartbeats = False

        self.escalation_endpoint_url = ""

        # Variable to hold background stop task.
        self._stop_task = utils.make_done_future()

        self.state = AlarmRuleState.UNCONFIGURED
        self.log.debug(f"AlarmRule:{self.salinfo.index} created.")

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
        if self.state != state:
            self.log.info(f"Transitioning from {self.state.name} to {state.name}.")
            self.state = state
            await self.evt_state.set_write(alarmName=self.rule_name, state=state.value)
            self.log.debug(f"Done transitioning to {state.name}.")

    async def start(self) -> None:
        """Finish construction and start running the alarm rule."""
        await super().start()

        await self._wait_for_task_done(self._heartbeat_task)
        self._should_produce_heartbeats = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self.log.info(f"AlarmRule:{self.salinfo.index} started.")

    async def _run(self) -> None:
        """Run the alarm rule."""
        try:
            await self._set_state(AlarmRuleState.RUNNING)
            self._should_be_running = asyncio.Future()
            await self.model.enable()
            await self._should_be_running
        except asyncio.CancelledError:
            # Deliberately ignore.
            pass
        except BaseException as e:
            if not isinstance(e, salobj.ExpectedError):
                self.log.exception("Error in run.")
            async with self._faling():
                await self.close_tasks()
        finally:
            if self.state not in [AlarmRuleState.FAILED, AlarmRuleState.STOPPING, AlarmRuleState.STOPPED]:
                await self._stop()

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

        await self.http_client.close()

    @contextlib.asynccontextmanager
    async def _stopping(self) -> typing.AsyncGenerator[None, None]:
        await self._set_state(AlarmRuleState.STOPPING)
        yield
        await self._set_state(AlarmRuleState.STOPPED)

    async def _stop(self) -> None:
        """Stop the alarm rule and all tasks."""
        async with self._stopping():
            await self.close_tasks()
        self._close_task = asyncio.create_task(self.close())
        await self._close_task

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
            self.escalation_endpoint_url = config.escalation_url

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

        self.log.debug("Sending cmd_run.ack_in_progress")
        await self.cmd_run.ack_in_progress(data=data, timeout=ACK_IN_PROGRESS_WAIT_TIME)
        self.log.debug("Done sending cmd_run.ack_in_progress")

        expected_state = AlarmRuleState.CONFIGURED
        if self.state != expected_state:
            raise UnexpectedAlarmRuleStateError(
                f"Invalid AlarmRule state {self.state.name}; expected {expected_state.name}."
            )

        self._run_task = asyncio.create_task(self._run())

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
        if not self._stop_task.done():
            self.log.warning(f"{self.rule_name}:{self.salinfo.index} already stopping.")
            return

        self._stop_task = asyncio.create_task(self._stop())

    async def do_mute(self, data: type_hints.BaseMsgType) -> None:
        """Mute the alarm of this rule.

        Parameters
        ----------
        data : ``cmd_mute.DataType``
            The data for the mute command.
        """
        self.log.info(f"do_mute {data.alarmName=}, {data.severity=}, {data.muteDuration=}, {data.mutedBy=}")
        await self.model.mute_alarm(
            name=data.alarmName, duration=data.muteDuration, severity=data.severity, user=data.mutedBy
        )

    async def do_unmute(self, data: type_hints.BaseMsgType) -> None:
        """Unmute the alarm of this rule.

        Parameters
        ----------
        data : ``cmd_unmute.DataType``
            The data for the unmute command.
        """
        self.log.info(f"do_unmute {data.alarmName=}")
        await self.model.unmute_alarm(name=data.alarmName)

    async def do_acknowledge(self, data: type_hints.BaseMsgType) -> None:
        """Acknowledge the alarm of this rule.

        Parameters
        ----------
        data : ``cmd_acknowledge.DataType``
            The data for the acknowledge command.
        """
        self.log.info(f"do_acknowledge {data.alarmName=}, {data.severity=}, {data.acknowledgedBy=}")
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
        self.log.info(f"do_unacknowledge {data.alarmName=}")
        await self.model.unacknowledge_alarm(name=data.alarmName)

    async def output_alarm(self, alarm):
        """Output the alarm event for one alarm."""
        if alarm.do_escalate:
            if not alarm.escalated_id and alarm.escalating_task.done():
                try:
                    alarm.escalating_task = asyncio.create_task(
                        asyncio.wait_for(
                            self.escalate_alarm(alarm),
                            timeout=self.model.config.escalation_timeout,
                        )
                    )
                    await alarm.escalating_task
                except asyncio.TimeoutError:
                    errmsg = "Timed out waiting for SquadCast"
                    alarm.escalated_id = f"Failed: {errmsg}"
                    self.log.warning(f"Could not escalate alarm {alarm}: {errmsg}")
                except RuntimeError as e:
                    self.log.error(f"Bug: escalation of {alarm} could not be attempted: {e!r}")
        else:
            if alarm.escalated_id:
                try:
                    await asyncio.wait_for(
                        self.deescalate_alarm(alarm),
                        timeout=self.model.config.escalation_timeout,
                    )
                except asyncio.TimeoutError:
                    self.log.warning(f"Could not de-escalate alarm {alarm}: timed out waiting for SquadCast")
                except Exception:
                    self.log.exception(f"Failed to de-escalate alarm {alarm}")
                finally:
                    alarm.escalated_id = ""

        self.log.debug(
            f"Outputting evt_alarm with {alarm.name=}, {alarm.severity=}, {alarm.reason=}, "
            f"{alarm.acknowledged=}, {alarm.muted=}, {alarm.escalated_id=}"
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

    async def escalate_alarm(self, alarm):
        """Escalate an alarm by creating a SquadCast incident.

        Store the ID of the alert in alarm.escalation_id.
        If the attempt fails, store an error message that begins with
        "Failed: " in alarm.escalation_id.

        If self.model.config.escalation_url is blank, then check the
        conditions in the Raises section but do nothing else.

        Raises
        ------
        RuntimeError
            If pre-conditions are not met (escalation is not attempted):

            * alarm.escalated_id is not blank: the alarm was already
              escalated (or at least an attempt was made).
            * alarm.do_escalate false: alarm should not be escalated.
            * alarm.escalation_responder empty: there is nobody to escalate
              the alarm to (so do_escalate should never have been set).
        """
        if alarm.escalated_id:
            raise RuntimeError("Alarm already escalated")
        if not alarm.do_escalate:
            raise RuntimeError("Alarm do_escalate false")
        if not alarm.escalation_responder:
            raise RuntimeError("Alarm escalation_responder empty")
        if self.model.config.escalation_url == "":
            return

        # Try to create a SquadCast incident
        try:
            escalated_id = str(uuid.uuid4())
            async with self.http_client.post(
                url=self.escalation_endpoint_url,
                json=dict(
                    status="trigger",
                    event_id=escalated_id,
                    message=f"Watcher alarm {alarm.name!r} escalated",
                    description=alarm.reason,
                    tags=dict(
                        responder=alarm.escalation_responder,
                        alarm_name=alarm.name,
                    ),
                ),
            ) as response:
                if response.status == HTTPStatus.ACCEPTED:
                    alarm.escalated_id = escalated_id
                else:
                    read_text = await response.text()
                    alarm.escalated_id = f"Failed: {read_text}"
                    self.log.warning(f"Could not escalate alarm {alarm}: {read_text}", exc_info=True)
        except Exception as e:
            errmsg = f"Could not reach SquadCast: {e!r}"
            alarm.escalated_id = f"Failed: {errmsg}"
            self.log.warning(f"Could not escalate alarm {alarm}: {errmsg}")

    async def deescalate_alarm(self, alarm):
        """De-escalate an alarm by resolving the associated SquadCast incident.

        Clear alarm.escalated_id and, if alarm.escalated_id is valid
        (does not start with "Failed"), tell SquadCast to close the alert.
        """
        if not alarm.escalated_id:
            return

        escalated_id = alarm.escalated_id
        alarm.escalated_id = ""
        if escalated_id.startswith("Failed") or self.model.config.escalation_url == "":
            # Nothing else to do
            return

        # Try to resolve the SquadCast incident
        async with self.http_client.post(
            url=self.escalation_endpoint_url,
            json=dict(
                status="resolve",
                event_id=escalated_id,
            ),
        ) as response:
            if response.status != HTTPStatus.ACCEPTED:
                read_text = await response.text()
                self.log.warning(
                    f"Could not resolve SquadCast incident {escalated_id} for alarm {alarm}: {read_text}"
                )

    @classmethod
    def make_from_cmd_line(cls) -> AlarmRuleRunner:
        """Creates an instance of the class using command-line arguments.

        This class method processes command-line arguments passed in as
        keyword arguments. It converts the specified arguments into parameters
        required to create an instance of the class.

        Returns
        -------
        AlarmRuleRunner
            Returns an instance of AlarmRuleRunner if the necessary arguments
            are correctly provided.

        Raises
        ------
        argparse.ArgumentError
            If there are issues with parsing command-line arguments.
        """
        parser = argparse.ArgumentParser(f"Run {cls.__name__} from the command line.")
        parser.add_argument(
            "rule_name",
            type=str,
            help="AlarmRuleRunner SAL Component name.",
        )
        parser.add_argument(
            "index",
            type=int,
            help="AlarmRuleRunner SAL Component index; must be unique among running AlarmRuleRunners",
        )
        args = parser.parse_args()

        return cls(rule_name=args.rule_name, index=args.index)

    @classmethod
    async def amain(cls) -> None:
        """Run an AlarmRuleRunner instance from the command line."""
        runner = cls.make_from_cmd_line()

        try:
            await runner.done_task
            await runner.close()
        except BaseException as e:
            # The runner failed in cleanup.
            if runner.state != AlarmRuleState.FAILED:
                warnings.warn(
                    f"AlarmRuleRunner failed in cleanup with {e!r}, "
                    f"but final state {runner.state!r} != FAILED",
                    RuntimeWarning,
                )
            sys.exit(1)

        if runner.state != AlarmRuleState.STOPPED:
            sys.exit(1)


def run_alarm_rule_runner():
    """Run an AlarmRuleRunner instance."""
    asyncio.run(AlarmRuleRunner.amain())
