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

__all__ = ["ThresholdHandler"]

import functools
import math

from lsst.ts import utils
from lsst.ts.xml.enums.Watcher import AlarmSeverity

from .base_rule import NoneNoReason

# Levels must be separated by hysteresis * HYSTERESIS_GROW_FACTOR,
# to provide some buffer between levels.
HYSTERESIS_GROW_FACTOR = 1.1


class ThresholdHandler:
    """Compute severity for a rule that involves one float value
    with multiple threshold levels.

    Parameters
    ----------
    warning_level : `float` | `None`
        Warning level. None to not use this level.
    serious_level : `float` | `None`
        Serious level. None to not use this level.
    critical_level : `float` | `None`
        Critical level. None to not use this level.
    warning_period : `float`
        Period after which a warning alarm is raised.
    serious_period : `float`
        Period after which a serious alarm is raised.
    critical_period : `float`
        Period after which a critical alarm is raised.
    hysteresis : `float`
        The amount by which the measurement must decrease below
        (or increase above if ``big_is_bad`` false) a severity level,
        before alarm severity is decreased.
    big_is_bad : `bool`
        True if measured values larger than the specified levels are bad;
        examples include most humidity, temperature, and vacuum measurements.
        False if measured values smaller than the levels are bad;
        the classic example is dew point depression.
    value_name : `str`
        Name of the value, e.g. "humidity" or "dew point depression".
    units : `str`
        Units of measurement.
    value_format : `str`, optional
        Format for float value (threshold level or measured value)
        without a leading colon, e.g. "0.2f"
    warning_msg : `str`, optional
        The first part of the reason string for a warning alarm.
        This should say what the operators should do.
    serious_msg : `str`, optional
        The first part of the reason string for a serious alarm.
        This should say what the operators should do.
    critical_msg : `str`, optional
        The first part of the reason string for a critical alarm.
        This should say what the operators should do.

    Raises
    ------
    ValueError
        If:

        * All levels are None.
        * ``hysteresis`` is not positive.
        * The non-None levels are not strictly ordered,
          or are separated by less than ``hysteresis`` * 1.1.
        * hysteresis or any non-None level is not finite.
    """

    def __init__(
        self,
        warning_level,
        serious_level,
        critical_level,
        warning_period,
        serious_period,
        critical_period,
        hysteresis,
        big_is_bad,
        value_name,
        units,
        value_format="0.2f",
        warning_msg="",
        serious_msg="",
        critical_msg="",
    ):
        if not math.isfinite(hysteresis):
            raise ValueError(f"hysteresis={hysteresis} must be finite.")
        if hysteresis < 0:
            raise ValueError(f"hysteresis={hysteresis} must be nonnegative.")

        # Handle ``big_is_bad`` false by "scaling", meaning flipping the sign,
        # of the levels and hysteresis. That allows using consistent comparison
        # operators, e.g. >, instead of changing them based on ``big_is_bad``.
        self.hysteresis = hysteresis
        self.scale = 1 if big_is_bad else -1
        self.value_name = value_name
        self.units = units
        self.value_format = value_format
        try:
            f"{1.0:{value_format}}"
        except ValueError:
            raise ValueError(f"value_format={value_format} is not a valid float value format")
        self.main_msg_dict = {
            severity: msg + ": "
            for severity, msg in (
                (AlarmSeverity.WARNING, warning_msg),
                (AlarmSeverity.SERIOUS, serious_msg),
                (AlarmSeverity.CRITICAL, critical_msg),
            )
            if msg
        }

        unused_level_names = []
        severity_scaled_level_dict = {}
        for severity, level in (
            (AlarmSeverity.CRITICAL, critical_level),
            (AlarmSeverity.SERIOUS, serious_level),
            (AlarmSeverity.WARNING, warning_level),
        ):
            arg_name = severity.name.lower() + "_level"
            if level is None:
                unused_level_names.append(arg_name)
            else:
                if not math.isfinite(level):
                    raise ValueError(f"{arg_name}={level} must be finite.")
                severity_scaled_level_dict[severity] = level * self.scale

        if not severity_scaled_level_dict:
            raise ValueError(
                "At least one of warning_level, serious_level, or critical_level must be specified."
            )
        # Dict of severity: scaled threshold level, sorted by decreasing
        # severity, and only including severities that have threshold levels.
        self.severity_scaled_level_dict = severity_scaled_level_dict

        # Test that levels are ordered and more than
        # ``hysteresis * HYSTERESIS_GROW_FACTOR`` apart.
        prev_severity_scaled_level = None
        grown_hysteresis = self.hysteresis * HYSTERESIS_GROW_FACTOR
        for severity, scaled_level in severity_scaled_level_dict.items():
            level = scaled_level * self.scale
            if prev_severity_scaled_level is None:
                prev_severity_scaled_level = (severity, scaled_level)
                continue
            prev_severity, prev_scaled_level = prev_severity_scaled_level
            prev_level = prev_scaled_level * self.scale
            if prev_scaled_level <= scaled_level or prev_scaled_level - grown_hysteresis <= scaled_level:
                # Something is wrong.
                # I defer message formatting until we know there's a problem,
                # to save a bit of time. It does mean testing one of the error
                # conditions twice, but once we are raising an exception,
                # time no longer is as important.
                if unused_level_names:
                    unused_levels_descr = f" (ignoring unused levels {', '.join(unused_level_names)}"
                else:
                    unused_levels_descr = ""
                levels_descr = (
                    f"{severity.name.lower()}_level={level} and "
                    f"{prev_severity.name.lower()}_level={prev_level}"
                )
                if prev_scaled_level <= scaled_level:
                    raise ValueError(f"{levels_descr} are out of order{unused_levels_descr}.")
                else:
                    raise ValueError(
                        f"{levels_descr} are not separated by at least "
                        f"hysteresis={hysteresis} * {HYSTERESIS_GROW_FACTOR}"
                        f"{unused_levels_descr}."
                    )
            prev_severity_scaled_level = (severity, scaled_level)

        # Keep track of level periods.
        self.level_periods = {
            AlarmSeverity.WARNING: warning_period,
            AlarmSeverity.SERIOUS: serious_period,
            AlarmSeverity.CRITICAL: critical_period,
        }
        # Dict of TAI time [UNIX seconds] and value to determine if there were
        # too large changes during an established time interval.
        self.value_dict: dict[float, float] = {}

    def get_severity_reason(self, value, current_severity, source_descr):
        """Compute alarm severity and reason string.

        Parameters
        ----------
        value : `float`
            Value to test, in the same units as the severity levels.
        current_severity : `AlarmSeverity`
            Current alarm severity.
        source_descr : `str`
            The source of the measurement; typcally a sensor location,
            for example "strut 1". If there is only one possible source
            then you may specify "" to not report it.
        """
        scaled_value = value * self.scale

        make_severity_reason = functools.partial(
            self._make_severity_reason,
            value=value,
            source_descr=source_descr,
        )

        tai_now = self.get_current_tai()
        for severity, scaled_level in self.severity_scaled_level_dict.items():
            if math.isclose(self.level_periods[severity], 0.0):
                # Immediately trigger an alarm if a value exceeds a threshold.
                if scaled_value > scaled_level:
                    return make_severity_reason(severity=severity, with_hysteresis=False)
                elif current_severity == severity and scaled_value > scaled_level - self.hysteresis:
                    return make_severity_reason(severity=severity, with_hysteresis=True)
            else:
                # Only trigger an alarm if the change in a value exceeds a
                # threshold within the given time range.
                self.value_dict[tai_now] = value
                # Remove too old items.
                self.value_dict = {
                    time: temp
                    for time, temp in self.value_dict.items()
                    if tai_now - time < self.level_periods[severity]
                }
                # Get all temperatures.
                temperatures = [temp for temp in self.value_dict.values()]
                # Determine if the temp change is too high.
                if max(temperatures) - min(temperatures) > scaled_level:
                    return make_severity_reason(severity=severity, with_hysteresis=False)

        return NoneNoReason

    def get_current_tai(self) -> float:
        """Get the current TAI time [UNIX seconds].

        This method is designed to be overridden in unit tests.

        Returns
        -------
        float
            The current TAI time [UNIX seconds].

        """
        return utils.current_tai()

    def get_test_value_severities(self):
        """Get a list of (value, expected_severity), for testing.

        You must apply the values in the specified order,
        in order to get the expected severities.

        The order is as follows (only taking into account the
        thresholds that are actually being used)::

            for starting threshold from most to least serious:
                for each threshold from starting to least serious:
                    if starting threshold:
                        value just above starting threshold level
                    else:
                        value just high enough to retain previous severity
                    value just low enough to drop to the next severity
                    value just high enough to retain that severity
                value just low enough to drop to severity NONE
        """
        # An additive buffer used near each threshold level.
        # This value must be smaller than
        # hysteresis * (1-HYSTERESIS_GROW_FACTOR)
        # to ensure that the returned levels are properly ordered.
        epsilon = self.hysteresis * (HYSTERESIS_GROW_FACTOR - 1) * 0.1
        severity_list = list(self.severity_scaled_level_dict.keys())
        scaled_value_severity_list = []
        for start_ind in range(len(self.severity_scaled_level_dict)):
            prev_scaled_level = None
            for severity in severity_list[start_ind:]:
                scaled_level = self.severity_scaled_level_dict[severity]
                if prev_scaled_level is not None:
                    # Append the largest value that should drop to this
                    # severity from the previous (higher) severity.
                    scaled_value_severity_list.append(
                        (prev_scaled_level - self.hysteresis - epsilon, severity)
                    )
                else:
                    # Append the smallest value that should trigger this
                    # severity (just above the threshold level).
                    scaled_value_severity_list.append((scaled_level + epsilon, severity))
                # Append the smallest value that keeps this severity triggered
                # (almost hysteresis below the threshold level).
                scaled_value_severity_list.append((scaled_level - self.hysteresis + epsilon, severity))
                prev_scaled_level = scaled_level

            # Append the largest value that will drop to severity NONE
            scaled_value_severity_list.append(
                (
                    scaled_level - self.hysteresis - epsilon,
                    AlarmSeverity.NONE,
                )
            )

        # Unscale the levels and return the result
        return [
            (scaled_level * self.scale, severity) for scaled_level, severity in scaled_value_severity_list
        ]

    def _make_severity_reason(
        self,
        severity,
        with_hysteresis,
        value,
        source_descr,
    ):
        """Make (alarm severity, reason).

        Parameters
        ----------
        severity : `AlarmSeverity`
            Alarm severity; must be one of the severities
            for which there is a threshold level.
        with_hysteresis : `bool`
            Should the reason include hysteresis?
        value : `float`
            Value to format, in the same units as the severity levels.
        source_descr : `str`
            The source of the measurement; typcally a sensor location,
            for example "strut 1". If there is only one possible source
            then you may specify "" to not report it.
        """
        main_msg = self.main_msg_dict.get(severity, "")

        scaled_level = self.severity_scaled_level_dict.get(severity, None)
        if scaled_level is None:
            raise ValueError(f"There is no threshold level for severity {severity!r}")

        value_str = f"{self.value_name} {value:{self.value_format}} {self.units}"

        relation_str = " > " if self.scale > 0 else " < "

        threshold_level = scaled_level * self.scale
        threshold_str = f"{threshold_level:{self.value_format}}"

        if with_hysteresis:
            sign_str = "-" if self.scale > 0 else "+"
            hysteresis = self.hysteresis * self.scale
            hysteresis_str = f" {sign_str} hysteresis {hysteresis:{self.value_format}}"
        else:
            hysteresis_str = ""

        if source_descr:
            source_str = f" as reported by {source_descr}"
        else:
            source_str = ""
        reason = f"{main_msg}{value_str}{relation_str}{threshold_str}{hysteresis_str}{source_str}"

        return (severity, reason)
