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

__all__ = ["MTM1M3EGWFlow"]


import typing

import yaml

from lsst.ts import salobj, watcher
from lsst.ts.xml.enums.Watcher import AlarmSeverity


class MTM1M3EGWFlow(watcher.BaseRule):
    """Monitor M1M3 flow.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
    log : `logging.Logger`, optional
        Parent logger.
    """

    def __init__(self, config, log=None):
        remote_info_list = [
            watcher.RemoteInfo(
                name="MTM1M3TS",
                index=0,
                callback_names=["evt_summaryState", "evt_engineeringMode"],
            ),
            watcher.RemoteInfo(
                name="ESS",
                index=130,
                callback_names=["tel_flowMeter"],
            ),
        ]
        super().__init__(
            config=config,
            name="MTM1M3EGWFlow",
            remote_info_list=remote_info_list,
            log=log,
        )

        self._enabled = False
        self._engineering_mode = False
        self._flow_timestamp = 0
        self._flow_rate = 100000

        self._first_minimal_timestamp: float | None = None

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: 'http://json-schema.org/draft-07/schema#'
            description: Configuration for MTM1M3EGWFlow rule.
            type: object
            properties:
              minimal_flow_rate:
                description: >-
                  Minimal flow rate (in flow meter units, liter/min).
                type: number
                default: 100.0
              alarm_delay:
                description: >-
                  Alarm delay in seconds. Do not trigger alarm for this number
                  of seconds after detecting improper state.
                type: number
                default: 120.0
              severity:
                description: >-
                  Alarm severity defined in enum AlarmSeverity.
                type: integer
                default: 2
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    def compute_alarm_severity(
        self, data: salobj.BaseMsgType, **kwargs: typing.Any
    ) -> watcher.AlarmSeverityReasonType:
        """Compute and set alarm severity and reason.

        Returns
        -------
        None, if no change or unknown, or a tuple of two values:

        severity: `lsst.ts.xml.enums.Watcher.AlarmSeverity`
            The new alarm severity.
        reason : `str`
            Detailed reason for the severity, e.g. a string describing
            what value is out of range, and what the range is.
            If ``severity`` is ``NONE`` then this value is ignored (but still
            required) and the old reason is retained until the alarm is reset
            to ``nominal`` state.

        Notes
        -----
        You may return `NoneNoReason` if the alarm state is ``NONE``.
        """

        if hasattr(data, "summaryState"):
            self._enabled = data.summaryState == salobj.State.ENABLED
        elif hasattr(data, "engineeringMode"):
            self._engineering_mode = data.engineeringMode

        if self._enabled is False or self._engineering_mode is True:
            return watcher.NoneNoReason

        if hasattr(data, "flowRate"):
            self._flow_timestamp = data.private_sndStamp
            self._flow_rate = data.flowRate

            if self._flow_rate <= self.config.minimal_flow_rate and self._first_minimal_timestamp is None:
                self._first_minimal_timestamp = self._flow_timestamp
                return watcher.NoneNoReason

        if self._flow_rate >= self.config.minimal_flow_rate:
            self._first_minimal_timestamp = None
            return watcher.NoneNoReason

        if (
            self._first_minimal_timestamp is None
            or self._flow_timestamp - self._first_minimal_timestamp < self.config.alarm_delay
        ):
            return watcher.NoneNoReason

        return (
            AlarmSeverity(int(self.config.severity)),
            f"Low flow rate: {self._flow_rate:.2f}, minimum is {self.config.minimal_flow_rate:.2f}",
        )
