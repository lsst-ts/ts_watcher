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

__all__ = ["MTMirrorTemperature"]

import logging
import types
import typing

import numpy as np
import yaml

from lsst.ts import salobj, watcher
from lsst.ts.xml.enums.Watcher import AlarmSeverity

from ..base_rule import AlarmSeverityReasonType, NoneNoReason
from ..remote_info import RemoteInfo


class MTMirrorTemperature(watcher.PollingRule):
    """Monitor the mirror temperature of main telescope M2 is out of the normal
    range.

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
            poll_names=["tel_temperature"],
        )
        super().__init__(
            config,
            f"MTMirrorTemperature.{remote_name}",
            [remote_info],
            log=log,
        )

        self._remote: salobj.Remote | None = None

    @classmethod
    def get_schema(cls) -> dict[str, typing.Any]:
        schema_yaml = """
            $schema: 'http://json-schema.org/draft-07/schema#'
            description: Configuration for MTMirrorTemperature rule.
            type: object
            properties:
                ring:
                    description: >-
                        Limit of the ring temperature (degree C).
                    type: number
                    default: 25.0
                intake:
                    description: >-
                        Limit of the intake (plenum) temperature (degree C).
                    type: number
                    default: 25.0
                gradient:
                    description: >-
                        Limit of the gradient (or the variation of ring
                        temperatures, peak-to-valley) temperature (degree C).
                    type: number
                    default: 10.0
                poll_interval:
                    description: >-
                        Time delay between polling updates (second).
                    type: number
                    default: 1.0
                severity:
                    description: >-
                        Alarm severity defined in enum AlarmSeverity.
                    type: integer
                    default: 2

            required:
            - ring
            - intake
            - gradient
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

        sources = list()
        if self._remote.tel_temperature.has_data:
            data = self._remote.tel_temperature.get()

            temperature_ring = np.array(data.ring)
            if np.any(temperature_ring > self.config.ring):
                sources.append("ring")

            if (temperature_ring.max() - temperature_ring.min()) > self.config.gradient:
                sources.append("gradient")

            if np.any(np.array(data.intake) > self.config.intake):
                sources.append("intake/plenum")

        return (
            NoneNoReason
            if (len(sources) == 0)
            else (
                AlarmSeverity(int(self.config.severity)),
                "Mirror temperature out of normal range.",
            )
        )
