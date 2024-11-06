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

__all__ = ["MTMirrorSafety"]

import datetime
import typing

import yaml
from lsst.ts import salobj
from lsst.ts.xml.enums.Watcher import AlarmSeverity

from ..base_rule import AlarmSeverityReasonType, BaseRule, NoneNoReason
from ..remote_info import RemoteInfo


class MTMirrorSafety(BaseRule):
    """Monitor several M1M3 and MTDome items.

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
                name="MTM1M3TS",
                index=0,
                callback_names=["tel_glycolLoopTemperature", "tel_thermalData"],
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
            name="MTMirrorSafety",
            remote_info_list=remote_info_list,
            log=log,
        )

        # Booleans to determine if an alarm needs to be triggered or not.
        self._mtdome_aperture_open = True  # Assume open unless telemetry received.
        self._m1m3_temperature_difference_too_high = False
        self._m1m3_temperature_change_too_high = False
        self._mtmount_azimuth_in_range = False

        # Keep track of MTMount azimuth for logging purposes.
        self.mtmount_azimuth = 0

        # Dict of TAI time [UNIX seconds] and temperature to determine if
        # there were too large temperature changes during an established time
        # interval.
        self._m1m3_temp_dict_list: list[dict[float, float]] = [{}] * 96

        # Time limits and other thresholds.
        self.time_range_start = datetime.time(
            hour=self.config.time_range_start, tzinfo=datetime.UTC
        )
        self.time_range_end = datetime.time(
            hour=self.config.time_range_end, tzinfo=datetime.UTC
        )
        self.temperature_change_interval = self.config.temperature_change_interval
        self.mtdome_humidity_threshold = self.config.mtdome_humidity_threshold
        self.m1m3_temperature_difference_threshold = (
            self.config.m1m3_temperature_difference_threshold
        )
        self.m1m3_temperature_change_threshold = (
            self.config.m1m3_temperature_change_threshold
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
  temperature_change_interval:
    description: Time interval [s] within which temperatures may not change too much.
    type: number
  mtdome_humidity_threshold:
    description: Humidity threshold [%] for the MTDome above which an alarm will be triggered.
    type: number
  m1m3_temperature_difference_threshold:
    description:
      Temperature difference threshold [degC] for the M1M3 above which an alarm will be triggered.
      The difference is taken over all 96 absolute temperature measurements at a given moment.
    type: number
  m1m3_temperature_change_threshold:
    description:
      Temperature change threshold [degC] for the M1M3 above which an alarm will be triggered.
      The change is measured for each of the 96 absolute temperature values over the temp change interval.
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
  - temperature_change_interval
  - mtdome_humidity_threshold
  - m1m3_temperature_difference_threshold
  - m1m3_temperature_change_threshold
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
        csc_name, _, topic_name = topic_callback.topic_key

        match csc_name:
            case "MTDome":
                self.process_mtdome_data(data)
            case "MTM1M3TS":
                self.process_mtm1m3ts_data(topic_name, data)
            case "MTMount":
                self.process_mtmount_data(data)
            case _:
                # This case should never trigger.
                self.log.warning(f"Unknown {csc_name=}. Ignoring.")

        # No alarm if the MTDome is closed.
        if not self._mtdome_aperture_open:
            self.log.debug("MTDome aperture is closed. Not triggering alarm.")
            return NoneNoReason

        # No alarm if the MTMount azimuth is not within the configured range.
        if not self._mtmount_azimuth_in_range:
            self.log.debug(
                f"MTMount azimuth {self.mtmount_azimuth} not in range "
                f"<{self.mtmount_azimuth_low_threshold}, {self.mtmount_azimuth_high_threshold}>. "
                "Not triggering alarm."
            )
            return NoneNoReason

        return self.determine_severity_and_reason()

    def determine_alarm_state_and_reasons(self) -> tuple[bool, list[str]]:
        """Determine the alarm state and reasons.

        For each CSC it is determined whether an alarm state has been
        triggered. If yes, a reason for that CSC is appended to a list of
        reasons.

        Returns
        -------
        `bool`
            Whether there is an alarm state or not.
        `list`[`str`]
            The reason(s) why there is an alarm state. If there is no alarm
            state, the list will be empty.

        """
        reasons: list[str] = []
        in_alarm_state = False
        if self._m1m3_temperature_difference_too_high:
            in_alarm_state = in_alarm_state or True
            reasons.append("M1M3 absolute temperature difference too high")
        if self._m1m3_temperature_change_too_high:
            in_alarm_state = in_alarm_state or True
            reasons.append("M1M3 absolute temperature change too high")
        return in_alarm_state, reasons

    def determine_severity_and_reason(self) -> AlarmSeverityReasonType:
        """Determine the alarm severity and reason.

        Several conditions may trigger an alarm at the same time. If one or
        more are True then the alarm severity is set to CRITICAL and the reason
        is a combination of all conditions. Otherwise severity None and an
        empty reason are returned.

        Returns
        -------
        `AlarmSeverityReasonType`
            The alarm severity and reason.
        """
        in_alarm_state, reasons = self.determine_alarm_state_and_reasons()
        if in_alarm_state:
            self.log.debug(f"Trigger CRITICAL alarm for {reasons=}.")
            reason = ", ".join(reasons)
            return AlarmSeverity.CRITICAL, reason
        else:
            self.log.debug("No thresholds exceeded. Not triggering alarm.")
            return NoneNoReason

    def get_temperature_change_too_high(
        self,
        temperature: float,
        threshold: float,
        timestamp: float,
        temp_dict: dict[float:float],
    ) -> bool:
        """Determine whether a temperature change was too high.

        First the temperature from the telemetry is added. Then too old
        temperatures are discarded. Finally it is determined whether the
        difference for the reamining temperatures is too high or not.

        Parameters
        ----------
        temperature : `float`
            The temperature [degC] from the telemetry.
        threshold : `float`
            The alarm threshold [degC].
        timestamp : `float`
            The TAI timestamp [UNIX seconds] of the temperature.
        temp_dict : `dict`[`float`, `float`]
            A dict with temperatures and their timestapms.

        Returns
        -------
        `bool`
            Whether the temperature difference is too high or not.
        """
        # Add new temperature.
        temp_dict[timestamp] = temperature

        # Remove too old items.
        temp_dict = {
            time: temp
            for time, temp in temp_dict.items()
            if timestamp - time < self.temperature_change_interval
        }

        # Get all temperatures.
        temperatures = [temp for temp in temp_dict.values()]
        # Determine if the temp change is too high.
        return max(temperatures) - min(temperatures) > threshold

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

    def process_mtm1m3ts_data(self, topic_name: str, data: salobj.BaseMsgType) -> None:
        """Process the M1M3 thermal system data.

        Parameters
        ----------
        topic_name : `str`
            The topic name.
        data : `salobj.BaseMsgType`
            The topic data.
        """
        absolute_temperatures = data.absoluteTemperature

        # Determine the temperature difference between the maximum and minimum
        # values of the array.
        self._m1m3_temperature_difference_too_high = (
            max(absolute_temperatures) - min(absolute_temperatures)
            > self.m1m3_temperature_difference_threshold
        )

        # Determine the temperature change over the configured period for each
        # value in the array.
        self._m1m3_temperature_change_too_high = False
        for i in range(len(absolute_temperatures)):
            if not self._m1m3_temp_dict_list[i]:
                m1m3_temp_dict: dict[float, float] = {}
                self._m1m3_temp_dict_list[i] = m1m3_temp_dict
            self._m1m3_temperature_change_too_high = (
                self._m1m3_temperature_change_too_high
                or self.get_temperature_change_too_high(
                    absolute_temperatures[i],
                    self.m1m3_temperature_change_threshold,
                    data.timestamp,
                    self._m1m3_temp_dict_list[i],
                )
            )
        print("WOUTER")

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
