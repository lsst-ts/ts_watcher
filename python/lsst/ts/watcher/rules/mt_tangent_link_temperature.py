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

__all__ = ["MTTangentLinkTemperature"]

import logging
import types
import typing

import numpy as np
import yaml
from lsst.ts import salobj, watcher
from lsst.ts.xml.enums.Watcher import AlarmSeverity

from ..base_rule import AlarmSeverityReasonType, NoneNoReason
from ..remote_info import RemoteInfo


class MTTangentLinkTemperature(watcher.PollingRule):
    """Monitor the tangent link temperature of main telescope M2 is out of the
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

        # ESS
        # 106 is the ESS SAL index for the M2 tangent link temperature
        remote_name_ess = "ESS"
        remote_info_ess = RemoteInfo(
            remote_name_ess,
            106,
            poll_names=["tel_temperature"],
        )

        # M2
        remote_name_m2 = "MTM2"
        remote_info_m2 = RemoteInfo(
            remote_name_m2,
            0,
            poll_names=["tel_temperature"],
        )

        super().__init__(
            config,
            f"MTTangentLinkTemperature.{remote_name_ess}",
            [remote_info_ess, remote_info_m2],
            log=log,
        )

        self._remote_ess: salobj.Remote | None = None
        self._remote_m2: salobj.Remote | None = None

        self._timeout = 0.0

    @classmethod
    def get_schema(cls) -> dict[str, typing.Any]:
        schema_yaml = """
            $schema: 'http://json-schema.org/draft-07/schema#'
            description: Configuration for MTTangentLinkTemperature rule.
            type: object
            properties:
                buffer:
                    description: >-
                        Buffer of the tangent link temperature compared with
                        the ambient (degree C).
                    type: number
                    default: 10.0
                timeout:
                    description: >-
                        Timeout of the telemetry data (second).
                    type: number
                    default: 3600.0
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
            - buffer
            - poll_interval
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    def setup(self, model) -> None:

        # 106 is the ESS SAL index for the M2 tangent link temperature
        self._remote_ess = model.remotes[("ESS", 106)]

        self._remote_m2 = model.remotes[("MTM2", 0)]

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

        assert self._remote_ess is not None
        assert self._remote_m2 is not None

        if (not self._remote_ess.tel_temperature.has_data) or (
            not self._remote_m2.tel_temperature.has_data
        ):
            self._timeout += 1.0
            return (
                NoneNoReason
                if self._timeout < self.config.timeout
                else (
                    AlarmSeverity.WARNING,
                    "Timeout of telemetry data.",
                )
            )

        self._timeout = 0.0

        # There are 16 channels in total. Only 6 are used for the M2 tangent
        # links. Other 10 elements are NaN.
        temperature_tangent_contain_nan = np.array(
            self._remote_ess.tel_temperature.get().temperatureItem
        )
        temperature_tangent = temperature_tangent_contain_nan[
            ~np.isnan(temperature_tangent_contain_nan)
        ]
        temperature_tangent.sort()

        temperature_ring = np.array(self._remote_m2.tel_temperature.get().ring)

        # Only consider the 3 active tangent links and ignore the other 3
        # hardpoints because they are passive with the lower temperatures.
        return (
            (
                AlarmSeverity(int(self.config.severity)),
                f"Tangent link temperature above ambient threshold of {self.config.buffer} degree C.",
            )
            if (
                np.all(
                    temperature_tangent[3:]
                    > (np.median(temperature_ring) + self.config.buffer)
                )
            )
            else NoneNoReason
        )
