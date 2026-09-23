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

__all__ = ["MTAOSLag"]

import math
import typing

import yaml

from lsst.ts import utils
from lsst.ts.xml.enums import MTAOS
from lsst.ts.xml.enums.Watcher import AlarmSeverity

from ..base_rule import AlarmSeverityReasonType, BaseRule, NoneNoReason
from ..remote_info import RemoteInfo

REASON = "Lag {} between MTAOS and MTCamera is above threshold {}."


class MTAOSLag(BaseRule):
    """Monitor the lag of MTAOs.

    If the lag is too high, raise an alarm. The lag is defined as the
    difference between the current visit ID and the visit ID of the last
    degree of freedom change. This only is important when in the closed loop.
    In open loop, the lag is not relevant.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
    log : `logging.Logger`, optional
        Parent logger.

    Notes
    -----
    The alarm name is "MTAOSLag".

    The current visitId is retrieved from the MTCamera CSC `endReadout` event.
    The visitId equals `imageDate` + `imageNumber` with the image date
    multiplied by 1e5 so a 13-digit int (converted from float) is obtained.

    The MTAOS visitId is retrieved from the `degreeOfFreedom` event as an int.
    """

    def __init__(self, config, log=None):
        remote_infos = [
            RemoteInfo(
                name="MTAOS",
                index=0,
                callback_names=["evt_closedLoopState", "evt_degreeOfFreedom"],
                poll_names=[],
                index_required=False,
            ),
            RemoteInfo(
                name="MTCamera",
                index=0,
                callback_names=["evt_endReadout"],
                poll_names=[],
                index_required=False,
            ),
        ]

        self.warning_lag_interval = config.warning_lag_interval
        self.serious_lag_interval = config.serious_lag_interval
        self.critical_lag_interval = config.critical_lag_interval
        self.lag_threshold = config.lag_threshold

        self.lag_start_tai = math.nan
        self.lag_amount = 0

        self.mtaos_closed_loop_state = None
        self.mtaos_dof_visit_id = 0
        self.camera_visit_id = 0

        super().__init__(
            config=config,
            name="MTAOSLag",
            remote_info_list=remote_infos,
            log=log,
        )

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            description: Configuration for MTAOSLag
            type: object
            properties:
              warning_lag_interval:
                description: >-
                  Interval in seconds after which lag in MTAOS may lead to a WARNING alarm.
                  Default is 30 seconds.
                type: number
                default: 30
              serious_lag_interval:
                description: >-
                  Interval in seconds after which lag in MTAOS may lead to a SERIOUS alarm.
                  Default is 60 seconds.
                type: number
                default: 60
              critical_lag_interval:
                description: >-
                  Interval in seconds after which lag in MTAOS may lead to a CRITIAL alarm.
                  Default is 120 seconds.
                type: number
                default: 120
              lag_threshold:
                description: >-
                  Threshold from which lag in MTAOS may may lead to an alarm.
                  Default is 5.
                type: number
                default: 5
        """
        return yaml.safe_load(schema_yaml)

    def compute_alarm_severity(self, **kwargs: typing.Any) -> AlarmSeverityReasonType:
        data = kwargs.get("data", None)
        assert data is not None

        data_vars = vars(data)

        # Get the MTAOS closed loop state.
        if "state" in data_vars:
            self.mtaos_closed_loop_state = MTAOS.ClosedLoopState(data_vars["state"])

        # Get the visitId of the degreesOfFreedom event.
        if "visitId" in data_vars:
            self.mtaos_dof_visit_id = data_vars["visitId"]

        # Get the visitId of the endReadout event.
        if "imageDate" in data_vars and "imageNumber" in data_vars:
            self.camera_visit_id = int(int(data_vars["imageDate"]) * 1e5 + data_vars["imageNumber"])

        self.log.debug(f"{self.camera_visit_id=}, {self.mtaos_dof_visit_id=}.")

        # Only raise an alarm when in closed loop.
        if self.mtaos_closed_loop_state not in [MTAOS.ClosedLoopState.IDLE, MTAOS.ClosedLoopState.ERROR]:
            self.log.debug("In closed loop.")

            self.lag_amount = self.camera_visit_id - self.mtaos_dof_visit_id
            self.log.debug(f"{self.lag_amount=}.")

            if self.lag_amount >= self.lag_threshold and math.isnan(self.lag_start_tai):
                # Only set the start tai if not set before.
                self.lag_start_tai = utils.current_tai()
                self.log.debug(f"{self.lag_start_tai=}.")
            elif self.lag_amount < self.lag_threshold:
                # Reset the start tai if there is no lag.
                self.lag_start_tai = math.nan

            # Determine the alarm severity.
            lag_duration = utils.current_tai() - self.lag_start_tai
            self.log.debug(f"{lag_duration=}.")
            reason = REASON.format(self.lag_amount, self.lag_threshold)
            if lag_duration >= self.critical_lag_interval:
                severity = AlarmSeverity.CRITICAL
            elif lag_duration >= self.serious_lag_interval:
                severity = AlarmSeverity.SERIOUS
            elif lag_duration >= self.warning_lag_interval:
                severity = AlarmSeverity.WARNING
            else:
                severity = AlarmSeverity.NONE
                reason = ""

            return severity, reason

        self.log.debug("Not in closed loop.")
        return NoneNoReason
