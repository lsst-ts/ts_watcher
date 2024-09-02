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

__all__ = ["MTM2ForceError"]

import logging
import types
import typing

import yaml
from lsst.ts import salobj, watcher
from lsst.ts.xml.enums.Watcher import AlarmSeverity

from ..base_rule import AlarmSeverityReasonType, NoneNoReason
from ..remote_info import RemoteInfo


class MTM2ForceError(watcher.PollingRule):
    """Monitor the actuator force error of main telescope M2 is out of the
    normal range.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
    log : `logging.Logger` or None, optional
        Parent logger. (the default is None)
    """

    def __init__(
        self, config: types.SimpleNamespace, log: logging.Logger | None = None
    ) -> None:

        remote_name = "MTM2"
        remote_info = RemoteInfo(
            remote_name,
            0,
            poll_names=["tel_axialForce", "tel_tangentForce"],
        )
        super().__init__(
            config,
            f"MTM2ForceError.{remote_name}",
            [remote_info],
            log=log,
        )

        self._remote: salobj.Remote | None = None

    @classmethod
    def get_schema(cls) -> dict[str, typing.Any]:
        schema_yaml = """
            $schema: 'http://json-schema.org/draft-07/schema#'
            description: Configuration for MTM2ForceError rule.
            type: object
            properties:
                force_error_axial:
                    description: >-
                        Limit of the force error of axial actuator (N).
                    type: number
                    default: 5.0
                force_error_tangent:
                    description: >-
                        Limit of the force error of tangent link (N).
                    type: number
                    default: 10.0
                poll_interval:
                    description: Time delay between polling updates (second).
                    type: number
                    default: 1.0

            required:
            - force_error_axial
            - force_error_tangent
            - poll_interval
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    def setup(self, model) -> None:

        self._remote = model.remotes[("MTM2", 0)]

    def compute_alarm_severity(self) -> AlarmSeverityReasonType:
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

        assert self._remote is not None

        list_axial = list()
        if self._remote.tel_axialForce.has_data:
            list_axial = self._check_out_of_range(
                self._remote.tel_axialForce.get(), self.config.force_error_axial
            )

        list_tangent = list()
        if self._remote.tel_tangentForce.has_data:
            list_tangent = self._check_out_of_range(
                self._remote.tel_tangentForce.get(), self.config.force_error_tangent
            )

        if (len(list_axial) != 0) and (len(list_tangent) != 0):
            return (
                AlarmSeverity.SERIOUS,
                f"Axial ({list_axial}) and tangent ({list_tangent}) force errors out of normal range.",
            )

        elif len(list_axial) != 0:
            return (
                AlarmSeverity.SERIOUS,
                f"Axial ({list_axial}) force error out of normal range.",
            )

        elif len(list_tangent) != 0:
            return (
                AlarmSeverity.SERIOUS,
                f"Tangent ({list_tangent}) force error out of normal range.",
            )

        else:
            return NoneNoReason

    def _check_out_of_range(
        self, data: salobj.BaseMsgType, threshold: float
    ) -> list[int]:
        """Check the data that is out of the range.

        Parameters
        ----------
        data : `salobj.BaseMsgType`
            Data.
        threshold : `float`
            Threshold in N.

        Returns
        -------
        list_actuators : `list`
            List of the actuators that are out of the range.
        """

        list_actuators = list()
        for idx in range(len(data.measured)):

            # Skip the hardpoints
            hardpoint_correction = data.hardpointCorrection[idx]
            if hardpoint_correction == 0.0:
                continue

            force_error = (
                data.lutGravity[idx]
                + data.lutTemperature[idx]
                + hardpoint_correction
                + data.applied[idx]
                - data.measured[idx]
            )
            if abs(force_error) > threshold:
                list_actuators.append(idx)

        return list_actuators
