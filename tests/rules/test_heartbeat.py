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

    async def test_operation(self):
        name = "ScriptQueue"
        index = 5
        timeout = 0.5

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
                rule_name = f"Heartbeat.{name}:{index}"
                rule = model.rules[rule_name]
                alarm = rule.alarm
                alarm.init_severity_queue()

                await controller.evt_heartbeat.write()
                await alarm.assert_next_severity(AlarmSeverity.NONE)
                assert alarm.nominal

                await asyncio.sleep(timeout / 2)
                await controller.evt_heartbeat.write()
                await alarm.assert_next_severity(AlarmSeverity.NONE)
                assert alarm.nominal

                await alarm.assert_next_severity(
                    AlarmSeverity.SERIOUS, timeout=timeout * 2.5
                )
                assert not alarm.nominal
                await controller.evt_heartbeat.write()
                await alarm.assert_next_severity(AlarmSeverity.NONE)
                assert not alarm.nominal
                assert alarm.max_severity == AlarmSeverity.SERIOUS
