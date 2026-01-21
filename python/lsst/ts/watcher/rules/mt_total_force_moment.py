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

__all__ = ["MTTotalForceMoment"]

import logging
import types
import typing

import yaml
from lsst.ts import salobj, watcher
from lsst.ts.xml.enums.Watcher import AlarmSeverity

from ..base_rule import AlarmSeverityReasonType, NoneNoReason
from ..remote_info import RemoteInfo


class MTTotalForceMoment(watcher.PollingRule):
    """Monitor the total force and moment of main telescope M2 is out of the
    normal range.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
    log : `logging.Logger` or None, optional
        Parent logger. (the default is None)
    """

    def __init__(self, config: types.SimpleNamespace, log: logging.Logger | None = None) -> None:
        remote_name = "MTM2"
        remote_info = RemoteInfo(
            remote_name,
            0,
            poll_names=["tel_netForcesTotal", "tel_netMomentsTotal"],
        )
        super().__init__(
            config,
            f"MTTotalForceMoment.{remote_name}",
            [remote_info],
            log=log,
        )

        self._remote: salobj.Remote | None = None

    @classmethod
    def get_schema(cls) -> dict[str, typing.Any]:
        schema_yaml = """
            $schema: 'http://json-schema.org/draft-07/schema#'
            description: Configuration for MTTotalForceMoment rule.
            type: object
            properties:
                fx:
                    description: >-
                        Limit of the total force in x-direction (N).
                    type: number
                    default: 115.0
                fy:
                    description: >-
                        Limit of the total force in y-direction (N).
                    type: number
                    default: 17600.0
                fz:
                    description: >-
                        Limit of the total force in z-direction (N).
                    type: number
                    default: 17600.0
                mx:
                    description: >-
                        Limit of the total moment in x-direction (N * m).
                    type: number
                    default: 1500.0
                my:
                    description: >-
                        Limit of the total moment in y-direction (N * m).
                    type: number
                    default: 40.0
                mz:
                    description: >-
                        Limit of the total moment in z-direction (N * m).
                    type: number
                    default: 300.0
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
            - fx
            - fy
            - fz
            - mx
            - my
            - mz
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

        list_forces = list()
        if self._remote.tel_netForcesTotal.has_data:
            list_forces = self._check_out_of_range(self._remote.tel_netForcesTotal.get(), ["fx", "fy", "fz"])

        list_moments = list()
        if self._remote.tel_netMomentsTotal.has_data:
            list_moments = self._check_out_of_range(
                self._remote.tel_netMomentsTotal.get(), ["mx", "my", "mz"]
            )

        severity = AlarmSeverity(int(self.config.severity))
        if list_forces and list_moments:
            return (
                severity,
                "Force and moment out of normal range.",
            )

        elif list_forces:
            return (
                severity,
                "Force out of normal range.",
            )

        elif list_moments:
            return (
                severity,
                "Moment out of normal range.",
            )

        else:
            return NoneNoReason

    def _check_out_of_range(self, data: salobj.BaseMsgType, components: list[str]) -> list[str]:
        """Check the data that is out of the range.

        Parameters
        ----------
        data : `salobj.BaseMsgType`
            Data.
        components : `list` [`str`]
            Components to check in data.

        Returns
        -------
        list_components : `list`
            List of the components that are out of the normal range.
        """

        list_components = list()
        for component in components:
            if abs(getattr(data, component)) > getattr(self.config, component):
                list_components.append(component)

        return list_components
