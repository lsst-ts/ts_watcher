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
from lsst.ts.idl.enums.Watcher import AlarmSeverity

STD_TIMEOUT = 5  # Max time to send/receive a topic (seconds)


class MTAirCompressorsStateTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()

    # Note: making this method async eliminates a warning in ts_utils.
    async def test_basics(self):
        schema = watcher.rules.MTAirCompressorsState.get_schema()
        assert schema is not None
        config = watcher.rules.MTAirCompressorsState.make_config()
        desired_rule_name = "MTAirCompressorsState"

        rule = watcher.rules.MTAirCompressorsState(config=config)
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
        minimal_config = watcher.rules.MTAirCompressorsState.make_config()
        assert minimal_config.one_severity == AlarmSeverity.WARNING
        assert minimal_config.both_severity == AlarmSeverity.CRITICAL

        # Check all values specified.
        for severity in AlarmSeverity:
            if severity == AlarmSeverity.NONE:
                continue

            with self.subTest(severity=severity):
                good_config = watcher.rules.MTAirCompressorsState.make_config(
                    both_severity=severity
                )
                assert good_config.both_severity == severity
                assert good_config.one_severity == AlarmSeverity.WARNING

                good_config = watcher.rules.MTAirCompressorsState.make_config(
                    one_severity=severity
                )
                assert good_config.one_severity == severity
                assert good_config.both_severity == AlarmSeverity.CRITICAL

        for bad_severity in (
            "not a number",
            AlarmSeverity.NONE,
            AlarmSeverity.CRITICAL + 1,
        ):
            with self.subTest(bad_severity=bad_severity):
                bad_config_dict = dict(one_severity=bad_severity)
                with pytest.raises(jsonschema.ValidationError):
                    watcher.rules.MTAirCompressorsState.make_config(**bad_config_dict)

                bad_config_dict = dict(both_severity=bad_severity)
                with pytest.raises(jsonschema.ValidationError):
                    watcher.rules.MTAirCompressorsState.make_config(**bad_config_dict)

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
        watcher_config_dict = yaml.safe_load(
            f"""
            disabled_sal_components: []
            auto_acknowledge_delay: 3600
            auto_unacknowledge_delay: 3600
            rules:
            - classname: MTAirCompressorsState
              configs:
              - one_severity: {one_severity.value}
                both_severity: {both_severity.value}
            escalation: []
            """
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)
        # Use index=0 so we can write to 1 or 2 as desired.
        async with salobj.Controller(name="MTAirCompressor", index=0) as controller:
            async with watcher.Model(
                domain=controller.domain, config=watcher_config
            ) as model:
                await model.enable()

                assert len(model.rules) == 1
                rule_name = "MTAirCompressorsState"
                rule = model.rules[rule_name]
                rule.alarm.init_severity_queue()

                # First set state for the main index; leaving
                # unknown state for the other index.
                for state in (
                    salobj.State.DISABLED,
                    salobj.State.STANDBY,
                    salobj.State.ENABLED,
                    salobj.State.FAULT,
                    salobj.State.DISABLED,
                ):
                    if state in {salobj.State.DISABLED, salobj.State.ENABLED}:
                        expected_severity = one_severity
                    else:
                        expected_severity = both_severity
                    await controller.evt_summaryState.set_write(
                        summaryState=state, salIndex=first_index, force_output=True
                    )
                    severity = await asyncio.wait_for(
                        rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT
                    )
                    assert severity == expected_severity
                    assert rule.alarm.severity_queue.empty()

                # Now set the state of the other index
                for state in (
                    salobj.State.DISABLED,
                    salobj.State.STANDBY,
                    salobj.State.ENABLED,
                    salobj.State.FAULT,
                    salobj.State.DISABLED,
                ):
                    if state in {salobj.State.DISABLED, salobj.State.ENABLED}:
                        expected_severity = AlarmSeverity.NONE
                    else:
                        expected_severity = one_severity
                    await controller.evt_summaryState.set_write(
                        summaryState=state, salIndex=second_index, force_output=True
                    )
                    severity = await asyncio.wait_for(
                        rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT
                    )
                    assert severity == expected_severity
                    assert rule.alarm.severity_queue.empty()
