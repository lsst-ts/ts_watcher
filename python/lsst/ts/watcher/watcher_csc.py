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

__all__ = ["WatcherCsc", "run_watcher"]

import asyncio
import os
import uuid
from http import HTTPStatus

import aiohttp
from lsst.ts import salobj

from . import __version__
from .config_schema import CONFIG_SCHEMA
from .model import Model

# URL suffix for the SquadCast Incident Webhook API
INCIDENT_WEBHOOK_URL_SUFFIX = "/v2/incidents/api/"


class WatcherCsc(salobj.ConfigurableCsc):
    """The Watcher CSC.

    Parameters
    ----------
    config_dir : `str`, optional
        Directory of configuration files, or None for the standard
        configuration directory (obtained from `get_default_config_dir`).
        This is provided for unit testing.
    initial_state : `salobj.State` or `int`, optional
        The initial state of the CSC. This is provided for unit testing,
        as real CSCs should start up in `lsst.ts.salobj.StateSTANDBY`,
        the default.
    override : `str`, optional
        Configuration override file to apply if ``initial_state`` is
        `State.DISABLED` or `State.ENABLED`.

    Raises
    ------
    salobj.ExpectedError
        If initial_state is invalid.
    """

    valid_simulation_modes = [0]
    enable_cmdline_state = True
    require_settings = True
    version = __version__

    def __init__(
        self, config_dir=None, initial_state=salobj.State.STANDBY, override=""
    ):
        # the Watcher model is created when the CSC is configured
        # and reset to None when the Watcher goes to standby.
        self.model = None
        self.http_client = aiohttp.ClientSession()

        super().__init__(
            "Watcher",
            index=0,
            config_schema=CONFIG_SCHEMA,
            config_dir=config_dir,
            initial_state=initial_state,
            override=override,
        )
        self.escalation_endpoint_url = ""

    @staticmethod
    def get_config_pkg():
        return "ts_config_ocs"

    async def close_tasks(self):
        await super().close_tasks()
        if self.model is not None:
            await self.model.close()
        await self.http_client.close()
        # aiohttp.ClientSession needs a bit more time to fully close.
        await asyncio.sleep(0.1)

    async def configure(self, config):
        if self.model is not None:
            # The model should be None, but if not, close it to get rid
            # of the old alarms.
            self.log.warning(
                "Model unexpectedly present while configuring the CSC. "
                "Closing the old model and building a new."
            )
            await self.model.close()
            self.model = None

        self.model = Model(
            domain=self.domain,
            config=config,
            alarm_callback=self.output_alarm,
            log=self.log,
        )
        if config.escalation_url:
            try:
                escalation_key = os.environ["ESCALATION_KEY"]
            except KeyError:
                raise RuntimeError(
                    "env variable ESCALATION_KEY must be set if config.escalation_url is set"
                )
            self.escalation_endpoint_url = (
                config.escalation_url + INCIDENT_WEBHOOK_URL_SUFFIX + escalation_key
            )

        await self.model.start_task

    async def escalate_alarm(self, alarm):
        """Escalate an alarm by creating a SquadCast incident.

        Store the ID of the alert in alarm.escalation_id.
        If the attempt fails, store an error message that begins with
        "Failed: " in alarm.escalation_id.

        If self.model.config.escalation_url is blank then check the conditions
        in the Raises section, but do nothing else.

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

        # Try to create an SquadCast incident
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
                    self.log.warning(f"Could not escalate alarm {alarm}: {read_text}")
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
                    f"Could not resolve SquadCast incident {escalated_id} "
                    f"for alarm {alarm}: {read_text}"
                )

    async def output_alarm(self, alarm):
        """Output the alarm event for one alarm."""
        if self.summary_state != salobj.State.ENABLED:
            return

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
                    self.log.error(
                        f"Bug: escalation of {alarm} could not be attempted: {e!r}"
                    )
        else:
            if alarm.escalated_id:
                try:
                    await asyncio.wait_for(
                        self.deescalate_alarm(alarm),
                        timeout=self.model.config.escalation_timeout,
                    )
                except asyncio.TimeoutError:
                    self.log.warning(
                        f"Could not de-escalate alarm {alarm}: timed out waiting for SquadCast"
                    )
                except Exception:
                    self.log.exception(f"Failed to de-escalate alarm {alarm}")
                finally:
                    alarm.escalated_id = ""

        await self.evt_alarm.set_write(
            name=alarm.name,
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

    async def handle_summary_state(self):
        if self.summary_state == salobj.State.ENABLED:
            if self.model is None:
                raise RuntimeError(
                    "Bug: state is ENABLED but there is no model. "
                    "Please restart the software and file a JIRA ticket."
                )
            await self.model.enable()
        elif self.summary_state == salobj.State.DISABLED:
            if self.model is None:
                raise RuntimeError(
                    "Bug: state is DISABLED but there is no model. "
                    "Please restart the software and file a JIRA ticket."
                )
            self.model.disable()
        else:
            if self.model is not None:
                await self.model.close()
                self.model = None

    async def do_acknowledge(self, data):
        self.assert_enabled()
        await self.model.acknowledge_alarm(
            name=data.name, severity=data.severity, user=data.acknowledgedBy
        )

    async def do_mute(self, data):
        """Mute one or more alarms."""
        self.assert_enabled()
        await self.model.mute_alarm(
            name=data.name,
            duration=data.duration,
            severity=data.severity,
            user=data.mutedBy,
        )

    async def do_showAlarms(self, data):
        """Show all alarms."""
        self.assert_enabled()
        for rule in self.model.rules.values():
            await self.output_alarm(rule.alarm)
            await asyncio.sleep(0.001)

    async def do_unacknowledge(self, data):
        """Unacknowledge one or more alarms."""
        self.assert_enabled()
        await self.model.unacknowledge_alarm(name=data.name)

    async def do_unmute(self, data):
        """Unmute one or more alarms."""
        self.assert_enabled()
        await self.model.unmute_alarm(name=data.name)

    async def do_makeLogEntry(self, data):
        """Make log entry for alarms."""
        self.assert_enabled()
        await self.model.make_log_entry(name=data.name)


def run_watcher():
    """Run the Watcher CSC."""
    asyncio.run(WatcherCsc.amain(index=None))
