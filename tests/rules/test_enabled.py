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
import itertools
import types
import unittest

import jsonschema
import pytest
import yaml
from lsst.ts import salobj, watcher
from lsst.ts.idl.enums.Watcher import AlarmSeverity

STD_TIMEOUT = 5  # Max time to send/receive a topic (seconds)


class EnabledTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()

    def test_basics(self):
        schema = watcher.rules.Enabled.get_schema()
        assert schema is not None
        name = "ScriptQueue"
        config = watcher.rules.Enabled.make_config(name=name)
        desired_rule_name = f"Enabled.{name}:0"

        rule = watcher.rules.Enabled(config=config)
        assert rule.name == desired_rule_name
        assert isinstance(rule.alarm, watcher.Alarm)
        assert rule.alarm.name == rule.name
        assert rule.alarm.nominal
        assert len(rule.remote_info_list) == 1
        remote_info = rule.remote_info_list[0]
        assert remote_info.name == name
        assert remote_info.index == 0
        assert name in repr(rule)
        assert "Enabled" in repr(rule)

    def test_config_validation(self):
        # Check defaults
        minimal_config_dict = dict(name="MTMount")
        minimal_config = watcher.rules.Enabled.make_config(**minimal_config_dict)
        assert minimal_config.name == minimal_config_dict["name"]
        assert minimal_config.disabled_severity == AlarmSeverity.WARNING
        assert minimal_config.standby_severity == AlarmSeverity.WARNING
        assert minimal_config.offline_severity == AlarmSeverity.SERIOUS
        assert minimal_config.fault_severity == AlarmSeverity.SERIOUS

        # Check all values specified
        good_config_dict = dict(
            name="ScriptQueue",
            disabled_severity=AlarmSeverity.SERIOUS,
            standby_severity=AlarmSeverity.SERIOUS,
            offline_severity=AlarmSeverity.CRITICAL,
            fault_severity=AlarmSeverity.CRITICAL,
        )
        good_config = watcher.rules.Enabled.make_config(**good_config_dict)
        for key, value in good_config_dict.items():
            assert getattr(good_config, key) == value

        for state, bad_value in itertools.product(
            salobj.State,
            ("not a number", AlarmSeverity.NONE, AlarmSeverity.CRITICAL + 1),
        ):
            if state == salobj.State.ENABLED:
                continue
            bad_config_dict = minimal_config_dict.copy()
            bad_config_dict[f"{state.name.lower()}_severity"] = bad_value
            with pytest.raises(jsonschema.ValidationError):
                watcher.rules.Enabled.make_config(**bad_config_dict)

    async def test_call(self):
        name = "ScriptQueue"
        index = 5

        # Use semi-realistic, but disparate, values for state severities.
        state_severity_dict = {
            salobj.State.DISABLED: AlarmSeverity.WARNING,
            salobj.State.STANDBY: AlarmSeverity.WARNING,
            salobj.State.OFFLINE: AlarmSeverity.SERIOUS,
            salobj.State.FAULT: AlarmSeverity.CRITICAL,
        }
        watcher_config_dict = yaml.safe_load(
            f"""
            disabled_sal_components: []
            auto_acknowledge_delay: 3600
            auto_unacknowledge_delay: 3600
            rules:
            - classname: Enabled
              configs:
              - name: {name}:{index}
                disabled_severity: {state_severity_dict[salobj.State.DISABLED].value}
                standby_severity: {state_severity_dict[salobj.State.STANDBY].value}
                offline_severity: {state_severity_dict[salobj.State.OFFLINE].value}
                fault_severity: {state_severity_dict[salobj.State.FAULT].value}
            escalation: []
            """
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)

        async with salobj.Controller(name=name, index=index) as controller:
            async with watcher.Model(
                domain=controller.domain, config=watcher_config
            ) as model:
                model.enable()

                assert len(model.rules) == 1
                rule_name = f"Enabled.{name}:{index}"
                rule = model.rules[rule_name]
                rule.alarm.init_severity_queue()

                for state in (
                    salobj.State.STANDBY,
                    salobj.State.DISABLED,
                    salobj.State.ENABLED,
                    salobj.State.FAULT,
                    salobj.State.STANDBY,
                    salobj.State.DISABLED,
                    salobj.State.FAULT,
                    salobj.State.STANDBY,
                    salobj.State.DISABLED,
                    salobj.State.ENABLED,
                ):
                    if state == salobj.State.ENABLED:
                        expected_severity = AlarmSeverity.NONE
                    else:
                        expected_severity = state_severity_dict[state]

                    await controller.evt_summaryState.set_write(
                        summaryState=state, force_output=True
                    )
                    severity = await asyncio.wait_for(
                        rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT
                    )
                    assert severity == expected_severity
                    assert rule.alarm.severity_queue.empty()
