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

STD_TIMEOUT = 5  # Max time to send/receive a topic (seconds)


class EnabledTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()

    def make_config(self, name):
        """Make a config for the Enabled rule.

        Parameters
        ----------
        name : `str`
            CSC name and index in the form `name` or `name:index`.
            The default index is 0.
        """
        schema = watcher.rules.Enabled.get_schema()
        validator = salobj.DefaultingValidator(schema)
        config_dict = dict(name=name)

        full_config_dict = validator.validate(config_dict)
        config = types.SimpleNamespace(**full_config_dict)
        for key in config_dict:
            assert getattr(config, key) == config_dict[key]
        return config

    async def test_basics(self):
        schema = watcher.rules.Enabled.get_schema()
        assert schema is not None
        name = "ScriptQueue"
        config = self.make_config(name=name)
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

    async def test_call(self):
        name = "ScriptQueue"
        index = 5

        watcher_config_dict = yaml.safe_load(
            f"""
            disabled_sal_components: []
            auto_acknowledge_delay: 3600
            auto_unacknowledge_delay: 3600
            rules:
            - classname: Enabled
              configs:
              - name: {name}:{index}
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
                    elif state == salobj.State.FAULT:
                        expected_severity = AlarmSeverity.SERIOUS
                    else:
                        expected_severity = AlarmSeverity.WARNING

                    await controller.evt_summaryState.set_write(
                        summaryState=state, force_output=True
                    )
                    severity = await asyncio.wait_for(
                        rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT
                    )
                    assert severity == expected_severity
                    assert rule.alarm.severity_queue.empty()
