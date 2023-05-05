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


class HeartbeatTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()

    def test_basics(self):
        schema = watcher.rules.Heartbeat.get_schema()
        assert schema is not None
        name = "ScriptQueue"
        timeout = 1.2
        config = watcher.rules.Heartbeat.make_config(
            name=name, timeout=timeout, alarm_severity=3
        )
        desired_rule_name = f"Heartbeat.{name}:0"

        rule = watcher.rules.Heartbeat(config=config)
        assert rule.name == desired_rule_name
        assert isinstance(rule.alarm, watcher.Alarm)
        assert rule.alarm.name == rule.name
        assert rule.alarm.nominal
        assert len(rule.remote_info_list) == 1
        remote_info = rule.remote_info_list[0]
        assert remote_info.name == name
        assert remote_info.index == 0
        assert name in repr(rule)
        assert "Heartbeat" in repr(rule)

    def test_config_validation(self):
        # Check defaults
        minimal_config_dict = dict(name="MTMount")
        minimal_config = watcher.rules.Heartbeat.make_config(**minimal_config_dict)
        assert minimal_config.name == minimal_config_dict["name"]
        assert minimal_config.timeout == 5
        assert minimal_config.alarm_severity == AlarmSeverity.CRITICAL

        # Check all values specified
        good_config_dict = dict(
            name="ScriptQueue", timeout=1, alarm_severity=AlarmSeverity.SERIOUS
        )
        good_config = watcher.rules.Heartbeat.make_config(**good_config_dict)
        for key, value in good_config_dict.items():
            assert getattr(good_config, key) == value

        for bad_sub_config in (
            dict(timeout="not_a_number"),
            dict(alarm_severity=AlarmSeverity.NONE),
            dict(alarm_severity=AlarmSeverity.CRITICAL + 1),
            dict(alarm_severity="not_a_number"),
            dict(no_such_field=5),
        ):
            bad_config_dict = minimal_config_dict.copy()
            bad_config_dict.update(bad_sub_config)
            with pytest.raises(jsonschema.ValidationError):
                watcher.rules.Heartbeat.make_config(**bad_config_dict)

    async def test_operation(self):
        name = "ScriptQueue"
        index = 5
        timeout = 0.9
        alarm_severity = AlarmSeverity.CRITICAL

        watcher_config_dict = yaml.safe_load(
            f"""
            disabled_sal_components: []
            auto_acknowledge_delay: 3600
            auto_unacknowledge_delay: 3600
            rules:
            - classname: Heartbeat
              configs:
              - name: {name}:{index}
                timeout: {timeout}
                alarm_severity: {alarm_severity}
            escalation: []
            """
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)

        async with salobj.Controller(name=name, index=index) as controller:
            async with watcher.Model(
                domain=controller.domain, config=watcher_config
            ) as model:
                await model.enable()

                assert len(model.rules) == 1
                rule_name = f"Heartbeat.{name}:{index}"
                rule = model.rules[rule_name]
                alarm = rule.alarm
                alarm.init_severity_queue()

                # Write a heartbeat event and check severity=None.
                await controller.evt_heartbeat.write()
                await alarm.assert_next_severity(AlarmSeverity.NONE)
                assert alarm.nominal

                # Write a heartbeat event well before the timer expires,
                # and check severity=None.
                await asyncio.sleep(timeout / 2)
                await controller.evt_heartbeat.write()
                await alarm.assert_next_severity(AlarmSeverity.NONE)
                assert alarm.nominal

                # Wait until the alarm occurs.
                await alarm.assert_next_severity(alarm_severity, timeout=timeout * 2.5)
                assert not alarm.nominal
                assert alarm.max_severity == alarm_severity

                # Write a heartbeat event and check that severity is None
                # but that max_severity is still high (since the alarm
                # has not been acknowledged).
                await controller.evt_heartbeat.write()
                await alarm.assert_next_severity(AlarmSeverity.NONE)
                assert not alarm.nominal
                assert alarm.max_severity == alarm_severity
