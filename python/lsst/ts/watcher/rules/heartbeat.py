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

__all__ = ["Heartbeat"]

import asyncio
import typing

import yaml
from lsst.ts import salobj, utils, watcher
from lsst.ts.xml.enums.Watcher import AlarmSeverity


class Heartbeat(watcher.BaseRule):
    """Monitor the heartbeat event from a SAL component.

    Set alarm severity NONE whenever a heartbeat event arrives
    and SERIOUS if a heartbeat event does not arrive in time.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
    log : `logging.Logger`, optional
        Parent logger.

    Notes
    -----
    The alarm name is f"Heartbeat.{name}:{index}",
    where name and index are derived from ``config.name``.
    """

    def __init__(self, config, log=None):
        remote_name, remote_index = salobj.name_to_name_index(config.name)
        remote_info = watcher.RemoteInfo(
            name=remote_name,
            index=remote_index,
            callback_names=["evt_heartbeat"],
            poll_names=[],
        )
        super().__init__(
            config=config,
            name=f"Heartbeat.{remote_info.name}:{remote_info.index}",
            remote_info_list=[remote_info],
            log=log,
        )
        self.heartbeat_timer_task = utils.make_done_future()

    @classmethod
    def get_schema(cls):
        # NOTE: another option is to have separate time limits for
        # warning, serious and critical. But this requires up to 3 timers
        # for each CSC, which adds many more tasks that the CSC has to manage.
        schema_yaml = f"""
            $schema: 'http://json-schema.org/draft-07/schema#'
            description: Configuration for Heartbeat
            type: object
            properties:
                name:
                    description: >-
                        CSC name and index in the form `name` or `name:index`.
                        The default index is 0.
                    type: string
                timeout:
                    description: Maximum allowed time between heartbeat events (sec).
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
            - timeout
            - alarm_severity
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    def compute_alarm_severity(
        self, data: salobj.BaseMsgType, **kwargs: typing.Any
    ) -> watcher.AlarmSeverityReasonType:
        self.restart_timer()
        return watcher.NoneNoReason

    async def heartbeat_timer(self):
        """Heartbeat timer."""
        await asyncio.sleep(self.config.timeout)
        severity_reason = (
            self.config.alarm_severity,
            f"Heartbeat event not seen in {self.config.timeout} seconds",
        )
        severity, reason = self._get_publish_severity_reason(severity_reason)
        await self.alarm.set_severity(severity=severity, reason=reason)

    def restart_timer(self):
        """Start or restart the heartbeat timer."""
        self.heartbeat_timer_task.cancel()
        self.heartbeat_timer_task = asyncio.ensure_future(self.heartbeat_timer())

    def start(self):
        self.restart_timer()

    def stop(self):
        self.heartbeat_timer_task.cancel()
