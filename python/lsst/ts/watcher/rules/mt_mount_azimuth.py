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

__all__ = ["MTMountAzimuth"]

import datetime
import typing

import yaml
from lsst.ts import salobj
from lsst.ts.xml.enums.Watcher import AlarmSeverity

from ..base_rule import AlarmSeverityReasonType, BaseRule, NoneNoReason
from ..remote_info import RemoteInfo


class MTMountAzimuth(BaseRule):
    """Monitor MTMount azimuth.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
    log : `logging.Logger`, optional
        Parent logger.
    """

    def __init__(self, config, log=None):
        remote_info_list = [
            RemoteInfo(
                name="MTDome",
                index=0,
                callback_names=["tel_apertureShutter"],
                poll_names=[],
            ),
            RemoteInfo(
                name="MTMount",
                index=0,
                callback_names=["tel_azimuth"],
                poll_names=[],
            ),
        ]
        super().__init__(
            config=config,
            name="MTMountAzimuth",
            remote_info_list=remote_info_list,
            log=log,
        )

        # Booleans to determine if an alarm needs to be triggered or not.
        self._mtdome_aperture_open = True  # Assume open unless telemetry received.
        self._mtmount_azimuth_in_range = False

        # Keep track of MTMount azimuth for logging purposes.
        self.mtmount_azimuth = 0

        # Time limits and other thresholds.
        self.time_range_start = datetime.time(
            hour=self.config.time_range_start, tzinfo=datetime.UTC
        )
        self.time_range_end = datetime.time(
            hour=self.config.time_range_end, tzinfo=datetime.UTC
        )
        self.mtmount_azimuth_low_threshold = self.config.mtmount_azimuth_low_threshold
        self.mtmount_azimuth_high_threshold = self.config.mtmount_azimuth_high_threshold

    @classmethod
    def get_schema(cls):
        schema_yaml = """
$schema: http://json-schema.org/draft-07/schema#
description: Configuration for MTMirrorSafety rule.
type: object
properties:
  time_range_start:
    description: Start hour of the time range within which alarms may be triggered.
    type: number
  time_range_end:
    description: End hour of the time range within which alarms may be triggered.
    type: number
  mtmount_azimuth_low_threshold:
    description: Lower azimuth [deg] for the MTMount above which an alarm will be triggered.
    type: number
  mtmount_azimuth_high_threshold:
    description: Upper azimuth [deg] for the MTMount below which an alarm will be triggered.
    type: number
required:
  - time_range_start
  - time_range_end
  - mtmount_azimuth_low_threshold
  - mtmount_azimuth_high_threshold
additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    def get_now_utc(self) -> datetime.time:
        """Convenience method to get the current time in UTC.

        This method is designed to be mocked in unit tests.

        Returns
        -------
        `datetime.time`
            The current time with UTC as timezone.
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        return now.timetz()

    def compute_alarm_severity(
        self, data: salobj.BaseMsgType, **kwargs: typing.Any
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

        topic_callback = kwargs["topic_callback"]
        csc_name, _, _ = topic_callback.topic_key

        match csc_name:
            case "MTDome":
                self.process_mtdome_data(data)
            case "MTMount":
                self.process_mtmount_data(data)
            case _:
                # This case should never trigger.
                self.log.warning(f"Unknown {csc_name=}. Ignoring.")

        # No alarm if the MTMount azimuth is not within the configured range.
        if not self._mtmount_azimuth_in_range:
            self.log.debug(
                f"MTMount azimuth {self.mtmount_azimuth} not in range "
                f"<{self.mtmount_azimuth_low_threshold}, {self.mtmount_azimuth_high_threshold}>. "
                "Not triggering alarm."
            )
            return NoneNoReason

        if self._mtdome_aperture_open:
            dome_open = ""
            severity = AlarmSeverity.SERIOUS
        else:
            dome_open = " not"
            severity = AlarmSeverity.WARNING
        return (
            severity,
            f"MTMount azimuth is within range [{self.mtmount_azimuth_low_threshold}, "
            f"{self.mtmount_azimuth_high_threshold}] and dome is{dome_open} open.",
        )

    def process_mtdome_data(self, data: salobj.BaseMsgType) -> None:
        """Process the MTDome data.

        Determine whether the aperture shutter is open or not.

        Parameters
        ----------
        data : `salobj.BaseMsgType`
            The topic data.
        """
        self._mtdome_aperture_open = (
            data.positionActual[0] > 0 or data.positionActual[1] > 0
        )

    def process_mtmount_data(self, data: salobj.BaseMsgType) -> None:
        """Process the MTMount data.

        Determine whether the azimuth is in range or not.

        Parameters
        ----------
        data : `salobj.BaseMsgType`
            The topic data.
        """
        time_now = self.get_now_utc()

        # No need to check any further if outside of the alarm hours.
        if not self.time_range_start <= time_now <= self.time_range_end:
            self.log.debug(
                f"{time_now} outside of time range [{self.time_range_start}, "
                f"{self.time_range_end}]. Not triggering alarm."
            )
            self._mtmount_azimuth_in_range = False
            return

        self.log.debug(
            f"{time_now} inside time range [{self.time_range_start}, {self.time_range_end}]."
        )

        self.mtmount_azimuth = data.actualPosition
        self._mtmount_azimuth_in_range = (
            self.mtmount_azimuth_low_threshold
            < self.mtmount_azimuth
            < self.mtmount_azimuth_high_threshold
        )
