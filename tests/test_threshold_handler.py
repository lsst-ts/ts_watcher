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

import itertools
import math
import random
import unittest

import pytest
from lsst.ts import watcher
from lsst.ts.xml.enums.Watcher import AlarmSeverity

random.seed(314)


class ThresholdHandlerTestCase(unittest.IsolatedAsyncioTestCase):
    def test_specific_small_bad_values(self):
        """Test some manually selected small-is-bad values."""
        value_name = "small_is_bad_value"
        units = "parsec"
        warning_level = 3.0
        critical_level = 2.5
        hysteresis = 0.1
        source_descr = "the source of this value"
        handler = watcher.ThresholdHandler(
            warning_level=warning_level,
            serious_level=None,
            critical_level=critical_level,
            warning_period=0,
            serious_period=0,
            critical_period=0,
            hysteresis=hysteresis,
            big_is_bad=False,
            value_name=value_name,
            units=units,
        )

        epsilon = 0.01 * hysteresis
        current_severity = AlarmSeverity.NONE
        for value, expected_severity in [
            # Just above warning level
            (warning_level + epsilon, AlarmSeverity.NONE),
            # Just below warning level
            (warning_level - epsilon, AlarmSeverity.WARNING),
            # Still in hysteresis range
            (warning_level + hysteresis - epsilon, AlarmSeverity.WARNING),
            # Above hysteresis range
            (warning_level + hysteresis + epsilon, AlarmSeverity.NONE),
            # Just above the serious level
            (critical_level + epsilon, AlarmSeverity.WARNING),
            # Just below serious level
            (critical_level - epsilon, AlarmSeverity.CRITICAL),
            # Still in hysteresis range
            (critical_level + hysteresis - epsilon, AlarmSeverity.CRITICAL),
            # Just above hysteresis range
            (critical_level + hysteresis + epsilon, AlarmSeverity.WARNING),
            # Just above warning + hysteresis: back to normal
            (warning_level + hysteresis + epsilon, AlarmSeverity.NONE),
        ]:
            severity, reason = handler.get_severity_reason(
                value=value,
                current_severity=current_severity,
                source_descr=source_descr,
            )
            assert severity == expected_severity
            current_severity = severity

    def test_specific_big_bad_values(self):
        """Test some manually selected big-is-bad values."""
        value_name = "big_is_bad_value"
        units = "bales"
        warning_level = 95
        serious_level = 98
        hysteresis = 1
        source_descr = "the source of this value"
        handler = watcher.ThresholdHandler(
            warning_level=warning_level,
            serious_level=serious_level,
            critical_level=None,
            warning_period=0,
            serious_period=0,
            critical_period=0,
            hysteresis=hysteresis,
            big_is_bad=True,
            value_name=value_name,
            units=units,
        )

        epsilon = 0.01 * hysteresis
        current_severity = AlarmSeverity.NONE

        for value, expected_severity in [
            # Just below warning level
            (warning_level - epsilon, AlarmSeverity.NONE),
            # Just below warning level
            (warning_level + epsilon, AlarmSeverity.WARNING),
            # Still in hysteresis range
            (warning_level - hysteresis + epsilon, AlarmSeverity.WARNING),
            # Below hysteresis range
            (warning_level - hysteresis - epsilon, AlarmSeverity.NONE),
            # Just below the serious level
            (serious_level - epsilon, AlarmSeverity.WARNING),
            # Just above serious level
            (serious_level + epsilon, AlarmSeverity.SERIOUS),
            # Still in hysteresis range
            (serious_level - hysteresis + epsilon, AlarmSeverity.SERIOUS),
            # Juat below hysteresis range
            (serious_level - hysteresis - epsilon, AlarmSeverity.WARNING),
            # Just below warning + hysteresis: back to normal
            (warning_level - hysteresis - epsilon, AlarmSeverity.NONE),
        ]:
            severity, reason = handler.get_severity_reason(
                value=value,
                current_severity=current_severity,
                source_descr=source_descr,
            )
            assert severity == expected_severity
            current_severity = severity

    def test_specific_big_bad_values_with_time_period(self):
        """Test some manually selected big-is-bad values."""
        value_name = "big_is_bad_value"
        units = "bales"
        warning_level = 1
        serious_level = 2
        hysteresis = 0
        source_descr = "the source of this value"
        handler = watcher.ThresholdHandler(
            warning_level=warning_level,
            serious_level=serious_level,
            critical_level=None,
            warning_period=10,
            serious_period=10,
            critical_period=10,
            hysteresis=hysteresis,
            big_is_bad=True,
            value_name=value_name,
            units=units,
        )
        handler.get_current_tai = self.get_current_tai

        current_severity = AlarmSeverity.NONE

        value = 20
        self.current_tai = 100.0
        expected_severity = AlarmSeverity.NONE
        severity, reason = handler.get_severity_reason(
            value=value,
            current_severity=current_severity,
            source_descr=source_descr,
        )
        assert severity == expected_severity
        current_severity = severity

        value = 21.5
        self.current_tai = 101.0
        expected_severity = AlarmSeverity.WARNING
        severity, reason = handler.get_severity_reason(
            value=value,
            current_severity=current_severity,
            source_descr=source_descr,
        )
        assert severity == expected_severity
        current_severity = severity

    def get_current_tai(self) -> float:
        return self.current_tai

    def test_auto_generated_values(self):
        for all_levels_dict, big_is_bad in (
            (
                dict(
                    warning_level=-1.1,
                    serious_level=1.2,
                    critical_level=25,
                ),
                True,
            ),
            (
                dict(
                    warning_level=-2.1,
                    serious_level=-1.1,
                    critical_level=3.1,
                ),
                False,
            ),
        ):
            hysteresis = 0.1
            none_name_list = [None] + list(all_levels_dict)
            for none_name1, none_name2 in itertools.product(
                none_name_list, none_name_list
            ):
                levels_dict = all_levels_dict.copy()
                if none_name1 is not None:
                    levels_dict[none_name1] = None
                if none_name2 is not None:
                    levels_dict[none_name2] = None
                self.check_auto_generated_values(
                    **levels_dict, hysteresis=hysteresis, big_is_bad=big_is_bad
                )

    def check_auto_generated_values(
        self, warning_level, serious_level, critical_level, hysteresis, big_is_bad
    ):
        value_name = "stella"
        units = "dog years"
        source_descr = "made up"
        msg_dict = {
            AlarmSeverity.WARNING: "uh oh",
            AlarmSeverity.SERIOUS: "we've got trouble",
            AlarmSeverity.CRITICAL: "the sky is falling",
        }
        # Delete one randomly chosen messge to test handling
        # of empty <level>_msg arguments
        del_severity = random.choice(list(msg_dict.keys()))
        del msg_dict[del_severity]
        handler = watcher.ThresholdHandler(
            warning_level=warning_level,
            serious_level=serious_level,
            critical_level=critical_level,
            warning_period=0,
            serious_period=0,
            critical_period=0,
            hysteresis=hysteresis,
            big_is_bad=True,
            value_name=value_name,
            units=units,
            warning_msg=msg_dict.get(AlarmSeverity.WARNING),
            serious_msg=msg_dict.get(AlarmSeverity.SERIOUS),
            critical_msg=msg_dict.get(AlarmSeverity.CRITICAL),
        )
        current_severity = AlarmSeverity.NONE
        for value, expected_severity in handler.get_test_value_severities():
            severity, reason = handler.get_severity_reason(
                value=value,
                current_severity=current_severity,
                source_descr=source_descr,
            )
            assert severity == expected_severity
            current_severity = severity
            if severity == AlarmSeverity.NONE:
                assert reason == ""
            else:
                assert value_name in reason
                assert units in reason
                assert source_descr in reason
                msg = msg_dict.get(severity)
                if msg:
                    assert reason.startswith(msg + ": ")
                else:
                    assert ":" not in reason[0:2]

    def test_constructor_errors(self):
        value_name = "stella"
        units = "dog years"
        for big_is_bad in (False, True):
            # Need at least one non-None level
            with pytest.raises(ValueError):
                watcher.ThresholdHandler(
                    warning_level=None,
                    serious_level=None,
                    critical_level=None,
                    warning_period=0,
                    serious_period=0,
                    critical_period=0,
                    hysteresis=1,
                    big_is_bad=big_is_bad,
                    value_name=value_name,
                    units=units,
                )

            # Levels and hysteresis must be finite
            for bad_value in (math.nan, math.inf):
                good_kwargs = dict(
                    warning_level=1,
                    serious_level=2,
                    critical_level=3,
                    hysteresis=0.1,
                )
                for name in good_kwargs.keys():
                    bad_kwargs = good_kwargs.copy()
                    bad_kwargs[name] = bad_value
                    with pytest.raises(ValueError):
                        watcher.ThresholdHandler(
                            **bad_kwargs,
                            warning_period=0,
                            serious_period=0,
                            critical_period=0,
                            big_is_bad=big_is_bad,
                            value_name=value_name,
                            units=units,
                        )

            # Invalid value_format
            with pytest.raises(ValueError):
                watcher.ThresholdHandler(
                    warning_level=None,
                    serious_level=None,
                    critical_level=None,
                    warning_period=0,
                    serious_period=0,
                    critical_period=0,
                    hysteresis=1,
                    big_is_bad=big_is_bad,
                    value_name=value_name,
                    value_format="y",  # invalid
                    units=units,
                )

        # Levels out of order
        # Levels are lists warning, serious, critical
        for levels, big_is_bad in (
            ((1, 2, -1), True),
            ((1, -1, None), True),
            ((None, 1, -1), True),
            ((1, None, 0), True),
            ((1, 2, -1), False),
            ((-1, 1, None), False),
            ((None, -1, 1), False),
            ((-1, None, 0), False),
        ):
            assert len(levels) == 3
            levels_dict = {
                f"{name}_level": value
                for name, value in zip(("warning", "serious", "critical"), levels)
            }
            with pytest.raises(ValueError):
                watcher.ThresholdHandler(
                    **levels_dict,
                    warning_period=0,
                    serious_period=0,
                    critical_period=0,
                    hysteresis=0.1,
                    big_is_bad=big_is_bad,
                    value_name=value_name,
                    units=units,
                )

        # Levels separated by less than hysteresis * 1.1
        # Levels are lists warning, serious, critical
        for levels, big_is_bad in (
            ((1, 2, 3), True),
            ((1, 2, None), True),
            ((None, 2, 3), True),
            ((1, None, 2), True),
            ((-1, -2, -3), False),
            ((-1, -2, None), False),
            ((None, -2, -3), False),
            ((-1, None, -2), False),
        ):
            assert len(levels) == 3
            levels_dict = {
                f"{name}_level": value
                for name, value in zip(("warning", "serious", "critical"), levels)
            }
            with pytest.raises(ValueError):
                watcher.ThresholdHandler(
                    **levels_dict,
                    warning_period=0,
                    serious_period=0,
                    critical_period=0,
                    hysteresis=1 / 1.09,
                    big_is_bad=big_is_bad,
                    value_name=value_name,
                    units=units,
                )
