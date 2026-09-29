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

__all__ = ["MTImageIngestionLag"]

import math
import typing

import yaml

from lsst.ts.xml.enums.Watcher import AlarmSeverity

from ..base_rule import AlarmSeverityReasonType, BaseRule
from ..remote_info import RemoteInfo

REASON = "The image ingestion lag {} is at or above threshold {}."


class MTImageIngestionLag(BaseRule):
    """Monitor the lag of the MTCamera image ingestion.

    If the lag is too high, raise an alarm. The lag is defined as the
    difference between the visit IDs of the current and the last ingested
    image.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
    log : `logging.Logger`, optional
        Parent logger.
    """

    def __init__(self, config, log=None):
        remote_infos = [
            RemoteInfo(
                name="MTOODS",
                index=0,
                callback_names=["evt_imageInOODS"],
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

        self.warning_lag_threshold = config.warning_lag_threshold
        self.serious_lag_threshold = config.serious_lag_threshold
        self.critical_lag_threshold = getattr(config, "critical_lag_threshold", None)

        self.camera_visit_id = math.inf
        self.ingested_image_visit_id = math.inf

        super().__init__(
            config=config,
            name="MTImageIngestionLag",
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
              warning_lag_threshold:
                description: >-
                  Threshold from which lag in image ingestion will lead to a WARNING alarm.
                  Default is 8.
                anyOf:
                  - type: number
                  - type: "null"
                default: 8
              serious_lag_threshold:
                description: >-
                  Threshold from which lag in image ingestion will lead to a SERIOUS alarm.
                  Default is 16.
                anyOf:
                  - type: number
                  - type: "null"
                default: 16
              critical_lag_threshold:
                description: >-
                  Threshold from which lag in image ingestion may lead to a CRITIAL alarm.
                  No default is set so leaving this value unset means the value is None
                  and this alarm level is disabled.
                type: number
        """
        return yaml.safe_load(schema_yaml)

    def compute_alarm_severity(self, **kwargs: typing.Any) -> AlarmSeverityReasonType:
        data = kwargs.get("data", None)

        # Get the visitId of the endReadout event.
        if (image_date := getattr(data, "imageDate", None)) is not None and (
            image_number := getattr(data, "imageNumber", None)
        ) is not None:
            self.camera_visit_id = int(int(image_date) * 1e5 + image_number)

        # Get the visitId of the imageInOODS event.
        if (obs_id := getattr(data, "obsid", None)) is not None:
            obs_id_items = obs_id.split("_")
            self.ingested_image_visit_id = int(obs_id_items[2] + obs_id_items[3][1:])

        self.log.debug(f"{self.camera_visit_id=}, {self.ingested_image_visit_id=}.")

        lag_amount = self.camera_visit_id - self.ingested_image_visit_id
        self.log.debug(f"{lag_amount=}.")

        # Determine the alarm severity.
        if self.critical_lag_threshold is not None and lag_amount >= self.critical_lag_threshold:
            severity = AlarmSeverity.CRITICAL
            reason = REASON.format(lag_amount, self.critical_lag_threshold)
        elif self.serious_lag_threshold is not None and lag_amount >= self.serious_lag_threshold:
            severity = AlarmSeverity.SERIOUS
            reason = REASON.format(lag_amount, self.serious_lag_threshold)
        elif self.warning_lag_threshold is not None and lag_amount >= self.warning_lag_threshold:
            severity = AlarmSeverity.WARNING
            reason = REASON.format(lag_amount, self.warning_lag_threshold)
        else:
            severity = AlarmSeverity.NONE
            reason = ""

        return severity, reason
