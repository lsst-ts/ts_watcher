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

__all__ = ["MTForceError"]

import logging
import types
import typing

import yaml
from lsst.ts import salobj, watcher
from lsst.ts.xml.enums.Watcher import AlarmSeverity

from ..base_rule import AlarmSeverityReasonType, NoneNoReason
from ..remote_info import RemoteInfo


class MTForceError(watcher.PollingRule):
    """Monitor the actuator force error of main telescope M2 is out of the
    normal range.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
    log : `logging.Logger` or None, optional
        Parent logger. (the default is None)
    """

    def __init__(self, config: types.SimpleNamespace, log: logging.Logger | None = None) -> None:
        # M2
        remote_name_m2 = "MTM2"
        remote_info_m2 = RemoteInfo(
            remote_name_m2,
            0,
            poll_names=["tel_axialForce", "tel_tangentForce"],
        )

        # MTMount
        remote_name_mount = "MTMount"
        remote_info_mount = RemoteInfo(
            remote_name_mount,
            0,
            poll_names=["tel_azimuth", "tel_elevation"],
        )

        super().__init__(
            config,
            f"MTForceError.{remote_name_m2}",
            [remote_info_m2, remote_info_mount],
            log=log,
        )

        self._remote_m2: salobj.Remote | None = None
        self._remote_mtmount: salobj.Remote | None = None

    @classmethod
    def get_schema(cls) -> dict[str, typing.Any]:
        schema_yaml = """
            $schema: 'http://json-schema.org/draft-07/schema#'
            description: Configuration for MTForceError rule.
            type: object
            properties:
                force_error_axial:
                    description: >-
                        Limit of the force error of axial actuator (N).
                    type: number
                    default: 15.0
                force_error_tangent:
                    description: >-
                        Limit of the force error of tangent link (N).
                    type: number
                    default: 50.0
                max_num_axial:
                    description: >-
                        Maximum number of the axial actuators that can have the
                        excess force error.
                    type: number
                    default: 10
                max_num_tangent:
                    description: >-
                        Maximum number of the tangent links that can have the
                        excess force error.
                    type: number
                    default: 2
                threshold_mtmount_acceleration:
                    description: >-
                        Threshold of the MTMount acceleration. The force error
                        will not be checked if the acceleration is higher than
                        this threshold. This is to avoid the wrong alarm from
                        the overshoot of the control algorithm. The unit is
                        deg/s^2.
                    type: number
                    default: 0.05
                poll_interval:
                    description: >-
                        Time delay between polling updates (second).
                    type: number
                    default: 1.0
                severity:
                    description: >-
                        Alarm severity defined in enum AlarmSeverity.
                    type: integer
                    default: 3

            required:
            - force_error_axial
            - force_error_tangent
            - poll_interval
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    def setup(self, model) -> None:
        self._remote_m2 = model.remotes[("MTM2", 0)]
        self._remote_mtmount = model.remotes[("MTMount", 0)]

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

        assert self._remote_m2 is not None
        assert self._remote_mtmount is not None

        # If the acceleration is higher than the threshold, no need to check
        # the force error.
        if self._remote_mtmount.tel_azimuth.has_data and (
            abs(self._remote_mtmount.tel_azimuth.get().actualAcceleration)
            > self.config.threshold_mtmount_acceleration
        ):
            return NoneNoReason

        if self._remote_mtmount.tel_elevation.has_data and (
            abs(self._remote_mtmount.tel_elevation.get().actualAcceleration)
            > self.config.threshold_mtmount_acceleration
        ):
            return NoneNoReason

        # Check the force error
        list_axial = list()
        if self._remote_m2.tel_axialForce.has_data:
            list_axial = self._check_out_of_range(
                self._remote_m2.tel_axialForce.get(), self.config.force_error_axial
            )

        list_tangent = list()
        if self._remote_m2.tel_tangentForce.has_data:
            list_tangent = self._check_out_of_range(
                self._remote_m2.tel_tangentForce.get(), self.config.force_error_tangent
            )

        has_error_axial = len(list_axial) > self.config.max_num_axial
        has_error_tangent = len(list_tangent) > self.config.max_num_tangent

        severity = AlarmSeverity(int(self.config.severity))
        if has_error_axial and has_error_tangent:
            return (
                severity,
                "Axial and tangent force errors out of normal range.",
            )

        elif has_error_axial:
            return (
                severity,
                "Axial force error out of normal range.",
            )

        elif has_error_tangent:
            return (
                severity,
                "Tangent force error out of normal range.",
            )

        else:
            return NoneNoReason

    def _check_out_of_range(self, data: salobj.BaseMsgType, threshold: float) -> list[int]:
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
