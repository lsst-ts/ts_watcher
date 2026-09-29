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

__all__ = ["Telemetry"]

import asyncio
import math
import typing
from itertools import combinations

import yaml

from lsst.ts import salobj
from lsst.ts.xml.enums.Watcher import AlarmSeverity

from ..base_rule import AlarmSeverityReasonType, BaseRule, NoneNoReason
from ..remote_info import RemoteInfo


class Telemetry(BaseRule):
    """Monitor the presence of telemetry from a SAL component.

    Set alarm severity NONE whenever telemetry arrives and the configured level
    if the telemetry does not arrive in time.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
    log : `logging.Logger`, optional
        Parent logger.

    Notes
    -----
    The alarm name is Telemetry.{name}:{index},
    where name and index are derived from ``config.name``.

    If two or all timeouts have the same value, warnings are logged but no
    exception is raised.
    """

    def __init__(self, config, log=None):
        remote_name, remote_index = salobj.name_to_name_index(config.name)
        callback_name = config.callback_name
        remote_info = [
            RemoteInfo(
                name=remote_name,
                index=remote_index,
                callback_names=[callback_name],
                poll_names=[],
            ),
            RemoteInfo(
                name=remote_name,
                index=remote_index,
                callback_names=["evt_summaryState"],
                poll_names=[],
            ),
        ]
        super().__init__(
            config=config,
            name=f"Telemetry.{remote_name}:{remote_index}",
            remote_info_list=remote_info,
            log=log,
        )

        self.timeouts = {
            "warning_timeout": (getattr(self.config, "warning_timeout", None), AlarmSeverity.WARNING),
            "serious_timeout": (getattr(self.config, "serious_timeout", None), AlarmSeverity.SERIOUS),
            "critical_timeout": (getattr(self.config, "critical_timeout", None), AlarmSeverity.CRITICAL),
        }

        for timeout_name1, timeout_name2 in combinations(self.timeouts.keys(), 2):
            timeout1 = self.timeouts[timeout_name1][0]
            timeout2 = self.timeouts[timeout_name2][0]
            if timeout1 is not None and timeout2 is not None and math.isclose(timeout1, timeout2):
                self.log.warning(f"{timeout_name1} and {timeout_name2} have the same timeout {timeout1}.")

        self.telemetry_timer_tasks = []
        self.csc_should_receive_telemetry = False
        self.summary_states = [salobj.State[state] for state in self.config.summary_states]

    @classmethod
    def get_schema(cls):
        # NOTE: another option is to have separate time limits for
        # warning, serious and critical. But this requires up to 3 timers
        # for each CSC, which adds many more tasks that the CSC has to manage.
        schema_yaml = f"""
            $schema: 'http://json-schema.org/draft-07/schema#'
            description: Configuration for Telemetry.
            type: object
            properties:
                name:
                    description: >-
                        CSC name and index in the form `name` or `name:index`.
                        The default index is 0.
                    type: string
                callback_name:
                    description: >-
                        The name of the telemetry topic to monitor.
                    type: string
                summary_states:
                    description: >-
                        The summary states the CSC is in when sending telemetry.
                    type: array
                    minItems: 1
                    items:
                      type: string
                      enum:
                      - {salobj.State.DISABLED.name}
                      - {salobj.State.ENABLED.name}
                warning_timeout:
                    description: >-
                        Maximum allowed time between telemetry (sec) before a WARNING alarm is raised.
                    anyOf:
                    - type: number
                    - type: "null"
                serious_timeout:
                    description: >-
                        Maximum allowed time between telemetry (sec) before a SERIOUS alarm is raised.
                    anyOf:
                    - type: number
                    - type: "null"
                critical_timeout:
                    description: >-
                        Maximum allowed time between telemetry (sec) before a CRITICAL alarm is raised.
                    anyOf:
                    - type: number
                    - type: "null"
            required:
            - name
            - callback_name
            anyOf:
            - required: [warning_timeout]
            - required: [serious_timeout]
            - required: [critical_timeout]
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    def compute_alarm_severity(self, **kwargs: typing.Any) -> AlarmSeverityReasonType:
        data = kwargs.get("data", None)

        topic_callback = kwargs["topic_callback"]
        _, _, topic_name = topic_callback.topic_key
        if topic_name == "evt_summaryState":
            self.log.debug(f"Received evt_summaryState for {self.name} with summaryState={data.summaryState}")
            self.csc_should_receive_telemetry = data.summaryState in self.summary_states
            if not self.csc_should_receive_telemetry:
                self.stop_timers()
            else:
                self.restart_timers()
        elif self.csc_should_receive_telemetry:
            self.restart_timers()
        return NoneNoReason

    async def telemetry_timer(self, timeout, alarm_severity):
        """Telemetry timer.

        Parameters
        ----------
         timeout : `float`
            The timeout in seconds.
         alarm_severity : `AlarmSeverity`
            The alarm severity.
        """
        await asyncio.sleep(timeout)
        if self.csc_should_receive_telemetry:
            severity_reason = (
                alarm_severity,
                f"Telemetry {self.config.callback_name} not seen in {timeout} seconds",
            )
        else:
            severity_reason = NoneNoReason
        severity, reason = self._get_publish_severity_reason(severity_reason)
        await self.alarm.set_severity(severity=severity, reason=reason)

    def restart_timers(self):
        """Start or restart the telemetry timers."""
        self.stop_timers()

        for timeout in self.timeouts:
            timeout, alarm_severity = self.timeouts[timeout]
            if timeout:
                self.log.debug(f"(re)starting {alarm_severity} telemetry timer for {self.name}.")
                self.telemetry_timer_tasks.append(
                    asyncio.ensure_future(self.telemetry_timer(timeout, alarm_severity))
                )

    def stop_timers(self):
        self.log.debug(f"stopping {len(self.telemetry_timer_tasks)} telemetry timer(s) for {self.name}.")
        for telemetry_timer_task in self.telemetry_timer_tasks:
            telemetry_timer_task.cancel()

    def start(self):
        self.restart_timers()

    def stop(self):
        self.stop_timers()
