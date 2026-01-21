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


class PowerGeneratorRunningTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()

    async def test_basics(self):
        schema = watcher.rules.PowerGeneratorRunning.get_schema()
        assert schema is not None
        name = "ESS"
        salindex = "1"
        full_name = f"{name}:{salindex}"
        config = watcher.rules.PowerGeneratorRunning.make_config(name=full_name)
        desired_rule_name = f"{name}:{salindex}.PowerGeneratorRunning"

        rule = watcher.rules.PowerGeneratorRunning(config=config)
        assert rule.name == desired_rule_name
        assert isinstance(rule.alarm, watcher.Alarm)
        assert rule.alarm.name == rule.name
        assert rule.alarm.nominal
        assert len(rule.remote_info_list) == 1
        remote_info = rule.remote_info_list[0]
        assert remote_info.name == name
        assert remote_info.index == int(salindex)
        assert name in repr(rule)
        assert "PowerGeneratorRunning" in repr(rule)

    def test_config_validation(self):
        # Check defaults
        minimal_config_dict = dict(name="ESS:1")
        minimal_config = watcher.rules.PowerGeneratorRunning.make_config(**minimal_config_dict)
        assert minimal_config.name == minimal_config_dict["name"]
        assert minimal_config.severity == AlarmSeverity.WARNING.name

        # Check all values specified
        good_config_dict = dict(
            name="ESS:1",
            severity=AlarmSeverity.SERIOUS.name,
        )
        good_config = watcher.rules.PowerGeneratorRunning.make_config(**good_config_dict)
        for key, value in good_config_dict.items():
            assert getattr(good_config, key) == value

        for bad_severity_value in (
            "Warning",
            2,
            AlarmSeverity.WARNING,
            AlarmSeverity.WARNING.value,
        ):
            bad_config_dict = minimal_config_dict.copy()
            bad_config_dict["severity"] = bad_severity_value
            with pytest.raises(jsonschema.ValidationError):
                watcher.rules.PowerGeneratorRunning.make_config(**bad_config_dict)

    async def test_call(self):
        name = "ESS"
        index = 1

        watcher_config_dict = yaml.safe_load(
            f"""
            disabled_sal_components: []
            auto_acknowledge_delay: 3600
            auto_unacknowledge_delay: 3600
            rules:
            - classname: PowerGeneratorRunning
              configs:
              - name: {name}:{index}
                severity: {AlarmSeverity.WARNING.name}
            escalation: []
            """
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)

        async with salobj.Controller(name=name, index=index) as controller:
            async with watcher.Model(domain=controller.domain, config=watcher_config) as model:
                await controller.tel_agcGenset150.set_write(running=False, force_output=True)

                await asyncio.sleep(STD_TIMEOUT)

                await model.enable()

                assert len(model.rules) == 1
                rule_name = f"{name}:{index}.PowerGeneratorRunning"
                rule = model.rules[rule_name]
                rule.alarm.init_severity_queue()

                for running_state in (True, False, True, False):
                    if not running_state:
                        expected_severity = AlarmSeverity.NONE
                    else:
                        expected_severity = AlarmSeverity.WARNING

                    await controller.tel_agcGenset150.set_write(running=running_state, force_output=True)
                    severity = await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)
                    assert severity == expected_severity
                    assert rule.alarm.severity_queue.empty()
