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

import asyncio
import types
import unittest

import jsonschema
import pytest
import yaml
from lsst.ts import salobj, watcher
from lsst.ts.xml.enums.Watcher import AlarmSeverity

STD_TIMEOUT = 5  # Max time to send/receive a topic (seconds)
DEFAULT_MIN_PRESSURE = 9000


class MTAirCompressorsPressureTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()

    # Note: making this method async eliminates a warning in ts_utils.
    async def test_basics(self):
        schema = watcher.rules.MTAirCompressorsPressure.get_schema()
        assert schema is not None
        config = watcher.rules.MTAirCompressorsPressure.make_config()
        desired_rule_name = "MTAirCompressorsPressure"

        rule = watcher.rules.MTAirCompressorsPressure(config=config)
        assert rule.name == desired_rule_name
        assert isinstance(rule.alarm, watcher.Alarm)
        assert rule.alarm.name == rule.name
        assert rule.alarm.nominal
        assert len(rule.remote_info_list) == 1
        remote_info = rule.remote_info_list[0]
        assert remote_info.name == "MTAirCompressor"
        assert remote_info.index == 0
        assert desired_rule_name in repr(rule)

    def test_config_validation(self):
        # Check defaults.
        minimal_config = watcher.rules.MTAirCompressorsPressure.make_config()
        assert minimal_config.one_severity == AlarmSeverity.WARNING
        assert minimal_config.both_severity == AlarmSeverity.CRITICAL
        assert minimal_config.minimal_pressure == DEFAULT_MIN_PRESSURE

        # Check all values specified.
        for severity in AlarmSeverity:
            if severity == AlarmSeverity.NONE:
                continue

            with self.subTest(severity=severity):
                good_config = watcher.rules.MTAirCompressorsPressure.make_config(
                    both_severity=severity
                )
                assert good_config.both_severity == severity
                assert good_config.one_severity == AlarmSeverity.WARNING
                assert good_config.minimal_pressure == DEFAULT_MIN_PRESSURE

                good_config = watcher.rules.MTAirCompressorsPressure.make_config(
                    one_severity=severity
                )
                assert good_config.one_severity == severity
                assert good_config.both_severity == AlarmSeverity.CRITICAL
                assert good_config.minimal_pressure == DEFAULT_MIN_PRESSURE

        for bad_severity in (
            "not a number",
            AlarmSeverity.NONE,
            AlarmSeverity.CRITICAL + 1,
        ):
            with self.subTest(bad_severity=bad_severity):
                bad_config_dict = dict(one_severity=bad_severity)
                with pytest.raises(jsonschema.ValidationError):
                    watcher.rules.MTAirCompressorsPressure.make_config(
                        **bad_config_dict
                    )

                bad_config_dict = dict(both_severity=bad_severity)
                with pytest.raises(jsonschema.ValidationError):
                    watcher.rules.MTAirCompressorsPressure.make_config(
                        **bad_config_dict
                    )

        for bad_minimal_pressure in ("nan", "aaa", "default"):
            with self.subTest(minimal_pressure=bad_minimal_pressure):
                bad_config_dict = dict(minimal_pressure=bad_minimal_pressure)
                with pytest.raises(jsonschema.ValidationError):
                    watcher.rules.MTAirCompressorsPressure.make_config(
                        **bad_config_dict
                    )

    async def test_call(self):
        for first_index in (1, 2):
            await self.check_call(first_index=first_index)

    async def check_call(self, first_index):
        """Check operation with a specified instance first to report state.

        Parameters
        ----------
        first_index : `int`
            The index of the first instance to report state.
            Must be 1 or 2.
        """
        salobj.set_random_lsst_dds_partition_prefix()
        second_index = {1: 2, 2: 1}.get(first_index)

        # Use a non-default severities, even though that means they will
        # have to be inverted: with one bad state being worse than both.
        one_severity = AlarmSeverity.CRITICAL
        both_severity = AlarmSeverity.SERIOUS
        minimal_pressure = 1000
        watcher_config_dict = yaml.safe_load(
            f"""
            disabled_sal_components: []
            auto_acknowledge_delay: 3600
            auto_unacknowledge_delay: 3600
            rules:
            - classname: MTAirCompressorsPressure
              configs:
              - one_severity: {one_severity.value}
                both_severity: {both_severity.value}
                minimal_pressure: {minimal_pressure}
            escalation: []
            """
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)
        # Use index=0 so we can write to 1 or 2 as desired.
        async with salobj.Controller(name="MTAirCompressor", index=0) as controller:
            async with watcher.Model(
                domain=controller.domain, config=watcher_config
            ) as model:
                # Set state of the second index as ENABLED
                await controller.evt_summaryState.set_write(
                    summaryState=salobj.State.ENABLED, salIndex=1, force_output=True
                )
                await controller.evt_summaryState.set_write(
                    summaryState=salobj.State.ENABLED, salIndex=2, force_output=True
                )

                # set pressure
                await controller.tel_analogData.set_write(
                    linePressure=minimal_pressure - 1, salIndex=1, force_output=True
                )
                await controller.tel_analogData.set_write(
                    linePressure=minimal_pressure - 1, salIndex=2, force_output=True
                )

                await model.enable()

                assert len(model.rules) == 1
                rule_name = "MTAirCompressorsPressure"
                rule = model.rules[rule_name]
                rule.alarm.init_severity_queue()

                while True:
                    try:
                        severity = await asyncio.wait_for(
                            rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT
                        )
                        print(f"Discard {severity=}")
                    except asyncio.TimeoutError:
                        break

                # Iterate the pressure for the main index; leaving
                # the second index in standard pressure.
                for pressure in [
                    minimal_pressure + 1,
                    minimal_pressure - 1,
                    minimal_pressure + 1,
                    minimal_pressure - 1,
                    minimal_pressure + 1,
                ]:
                    if pressure > minimal_pressure:
                        expected_severity = one_severity
                    else:
                        expected_severity = both_severity
                    print(f"primary {pressure:.2f}::{expected_severity=!r}")
                    await controller.tel_analogData.set_write(
                        linePressure=pressure, salIndex=first_index, force_output=True
                    )
                    severity = await asyncio.wait_for(
                        rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT
                    )
                    assert severity == expected_severity
                    assert rule.alarm.severity_queue.empty()

                # Now set the pressure of the other index
                for pressure in [
                    minimal_pressure + 1,
                    minimal_pressure - 1,
                    minimal_pressure + 1,
                    minimal_pressure - 1,
                    minimal_pressure + 1,
                    minimal_pressure - 1,
                ]:
                    if pressure > minimal_pressure:
                        expected_severity = AlarmSeverity.NONE
                    else:
                        expected_severity = one_severity
                    print(f"secondary {pressure:.2f}::{expected_severity=!r}")
                    await controller.tel_analogData.set_write(
                        linePressure=pressure, salIndex=second_index, force_output=True
                    )
                    severity = await asyncio.wait_for(
                        rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT
                    )
                    assert severity == expected_severity
                    assert rule.alarm.severity_queue.empty()
