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

__all__ = ["Telemetry"]

import asyncio
import typing

import yaml

from lsst.ts import salobj, utils
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
    The alarm name is f"Telemetry.{name}:{index}",
    where name and index are derived from ``config.name``.
    The alarm severity is configurable as well as the amount of time after
    which the alarm will be raised.
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
        self.telemetry_timer_task = utils.make_done_future()
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
                timeout:
                    description: Maximum allowed time between telemetry (sec).
                    type: number
                    default: 15
                alarm_severity:
                    description: >-
                        Alarm severity if the time is exceeded. One of:
                        * {AlarmSeverity.WARNING.value} for warning
                        * {AlarmSeverity.SERIOUS.value} for serious
                        * {AlarmSeverity.CRITICAL.value} for critical
                    type: integer
                    enum:
                    - {AlarmSeverity.WARNING.value}
                    - {AlarmSeverity.SERIOUS.value}
                    - {AlarmSeverity.CRITICAL.value}
                    default: {AlarmSeverity.CRITICAL.value}
            required:
            - name
            - callback_name
            - timeout
            - alarm_severity
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    def compute_alarm_severity(
        self, data: salobj.BaseMsgType, **kwargs: typing.Any
    ) -> AlarmSeverityReasonType:
        topic_callback = kwargs["topic_callback"]
        _, _, topic_name = topic_callback.topic_key
        if topic_name == "evt_summaryState":
            self.log.debug(f"Received evt_summaryState for {self.name} with summaryState={data.summaryState}")
            self.csc_should_receive_telemetry = data.summaryState in self.summary_states
            if not self.csc_should_receive_telemetry:
                self.stop_timer()
            else:
                self.restart_timer()
        elif self.csc_should_receive_telemetry:
            self.restart_timer()
        return NoneNoReason

    async def telemetry_timer(self):
        """telemetry timer."""
        await asyncio.sleep(self.config.timeout)
        if self.csc_should_receive_telemetry:
            severity_reason = (
                self.config.alarm_severity,
                f"Telemetry {self.config.callback_name} not seen in {self.config.timeout} seconds",
            )
        else:
            severity_reason = NoneNoReason
        severity, reason = self._get_publish_severity_reason(severity_reason)
        await self.alarm.set_severity(severity=severity, reason=reason)

    def restart_timer(self):
        """Start or restart the telemetry timer."""
        self.stop_timer()
        self.log.debug("(re)starting telemetry timer.")
        self.telemetry_timer_task = asyncio.ensure_future(self.telemetry_timer())

    def stop_timer(self):
        self.log.debug("stopping telemetry timer.")
        self.telemetry_timer_task.cancel()

    def start(self):
        self.restart_timer()

    def stop(self):
        self.stop_timer()
