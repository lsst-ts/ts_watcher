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

__all__ = ["MTHexapodOvercurrent"]

import logging
import types
import typing

import yaml

from lsst.ts import salobj
from lsst.ts.xml.enums.MTHexapod import ControllerState, EnabledSubstate, SalIndex
from lsst.ts.xml.enums.Watcher import AlarmSeverity

from ..base_rule import AlarmSeverityReasonType, BaseRule, NoneNoReason
from ..remote_info import RemoteInfo


class MTHexapodOvercurrent(BaseRule):
    """Rule to monitor the main telescope hexapod overcurrent event.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
    log : `logging.Logger` or None, optional
        Parent logger. (the default is None)
    """

    # This is actually the max value of int32.
    MAX_COUNT = 2147483647

    def __init__(
        self,
        config: types.SimpleNamespace,
        log: logging.Logger | None = None,
    ):
        remote_name, remote_index = salobj.name_to_name_index(config.name)
        remote_info = RemoteInfo(
            name=remote_name,
            index=remote_index,
            callback_names=["evt_controllerState", "tel_electrical"],
        )
        super().__init__(
            config,
            f"MTHexapodOvercurrent.{remote_info.name}:{remote_info.index}",
            [remote_info],
            log=log,
        )

        self._hexapod = SalIndex(remote_index).name

        self._controller_state = ControllerState.STANDBY
        self._enabled_state = EnabledSubstate.STATIONARY

        self._count = 0

        # The telemetry rate is 20 Hz
        self._max_count = int(config.time_window * 60 * 20)

    @classmethod
    def get_schema(cls) -> dict[str, typing.Any]:
        schema_yaml = """
            $schema: 'http://json-schema.org/draft-07/schema#'
            description: Configuration for BaseHexapodOvercurrentRule rule.
            type: object
            properties:
                name:
                    description: >-
                        CSC name and index in the form `name` or `name:index`.
                        The default index is 0.
                    type: string
                threshold_current:
                    description: >-
                        Threshold of the current in ampere.
                    type: number
                    default: 4.0
                time_window:
                    description: >-
                        Maximum time window in minute to check the hexapod
                        current in idle. The telemetry rate is 20 Hz.
                        Therefore, 10 mins are 12000 times of telemetry.
                    type: number
                    default: 10
                severity:
                    description: >-
                        Alarm severity defined in enum AlarmSeverity.
                    type: integer
                    default: 2

            required:
            - name
            - threshold_current
            - time_window
            - severity
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    def compute_alarm_severity(
        self, data: salobj.BaseMsgType, **kwargs: dict[str, typing.Any]
    ) -> AlarmSeverityReasonType:
        """Compute and set alarm severity and reason.

        Parameters
        ----------
        data : `salobj.BaseMsgType`
              Message from the topic described by topic_callback.
        **kwargs : `dict` [`str`, `typing.Any`]
            Keyword arguments. If triggered by `TopicCallback` calling
            `update_alarm_severity`, the arguments will be as follows:

            * topic_callback : `TopicCallback`
              Topic callback wrapper.

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

        # Update the controller state and enabled substate
        if hasattr(data, "controllerState"):
            self._controller_state = ControllerState(data.controllerState)
            self._enabled_state = EnabledSubstate(data.enabledSubstate)

            if not self._is_enabled_and_stationary():
                self._count = 0

            return NoneNoReason

        # Check the current and update the count
        # In the normal operation, the motor current can be higher than the
        # threshold. Therefore, we only care about the condition that we always
        # have the motor current to be higher than the threshold all the time
        # when there is no movement.
        if self._is_enabled_and_stationary() and any(
            [current >= self.config.threshold_current for current in data.motorCurrent]
        ):
            self._count += 1 if (self._count < self.MAX_COUNT) else 0
        else:
            self._count -= 1 if (self._count > 0) else 0

        return (
            NoneNoReason
            if (self._count < self._max_count)
            else (
                AlarmSeverity(self.config.severity),
                f"{self._hexapod} overcurrent above threshold.",
            )
        )

    def _is_enabled_and_stationary(self) -> bool:
        """Controller is enabled and stationary or not.

        Returns
        -------
        `bool`
            True if the controller is enabled and stationary. Otherwise, False.
        """

        return (self._controller_state == ControllerState.ENABLED) and (
            self._enabled_state == EnabledSubstate.STATIONARY
        )
