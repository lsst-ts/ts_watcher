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


class PowerGeneratorFailTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()

    async def test_basics(self):
        schema = watcher.rules.PowerGeneratorFail.get_schema()
        assert schema is not None
        name = "ESS"
        salindex = "1"
        full_name_primary = f"{name}:{salindex}"
        full_name_secondary = f"{name}:{int(salindex) + 1}"
        config = watcher.rules.PowerGeneratorFail.make_config(
            name_primary=full_name_primary, name_secondary=full_name_secondary
        )
        desired_rule_name = f"{name}.PowerGeneratorFail"

        rule = watcher.rules.PowerGeneratorFail(config=config)
        assert rule.name == desired_rule_name
        assert isinstance(rule.alarm, watcher.Alarm)
        assert rule.alarm.name == rule.name
        assert rule.alarm.nominal
        assert len(rule.remote_info_list) == 2
        remote_info_primary = rule.remote_info_list[0]
        remote_info_secondary = rule.remote_info_list[1]
        assert remote_info_primary.name == name
        assert remote_info_primary.index == int(salindex)
        assert remote_info_secondary.name == name
        assert remote_info_secondary.index == int(salindex) + 1
        assert name in repr(rule)
        assert "PowerGeneratorFail" in repr(rule)

    def test_config_validation(self):
        # Check defaults
        minimal_config_dict = dict(name_primary="ESS:1", name_secondary="ESS:2")
        minimal_config = watcher.rules.PowerGeneratorFail.make_config(**minimal_config_dict)
        assert minimal_config.name_primary == minimal_config_dict["name_primary"]
        assert minimal_config.name_secondary == minimal_config_dict["name_secondary"]
        assert minimal_config.severity_individual_fail == AlarmSeverity.SERIOUS.name
        assert minimal_config.severity_both_fail == AlarmSeverity.CRITICAL.name

        # Check all values specified
        good_config_dict = dict(
            name_primary="ESS:1",
            name_secondary="ESS:2",
            severity_individual_fail=AlarmSeverity.SERIOUS.name,
            severity_both_fail=AlarmSeverity.CRITICAL.name,
        )
        good_config = watcher.rules.PowerGeneratorFail.make_config(**good_config_dict)
        for key, value in good_config_dict.items():
            assert getattr(good_config, key) == value

        for bad_severity_value in (
            "Warning",
            2,
            AlarmSeverity.WARNING,
            AlarmSeverity.WARNING.value,
        ):
            bad_config_dict = minimal_config_dict.copy()
            bad_config_dict["severity_individual_fail"] = bad_severity_value
            bad_config_dict["severity_both_fail"] = bad_severity_value
            with pytest.raises(jsonschema.ValidationError):
                watcher.rules.PowerGeneratorFail.make_config(**bad_config_dict)

    async def test_call(self):
        name = "ESS"
        index = 1
        full_name_primary = f"{name}:{index}"
        full_name_secondary = f"{name}:{index + 1}"

        watcher_config_dict = yaml.safe_load(
            f"""
            disabled_sal_components: []
            auto_acknowledge_delay: 3600
            auto_unacknowledge_delay: 3600
            rules:
            - classname: PowerGeneratorFail
              configs:
              - name_primary: {full_name_primary}
                name_secondary: {full_name_secondary}
                severity_individual_fail: {AlarmSeverity.SERIOUS.name}
                severity_both_fail: {AlarmSeverity.CRITICAL.name}
            escalation: []
            """
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)

        async with (
            salobj.Controller(name=name, index=index) as controllerprimary,
            salobj.Controller(name=name, index=index + 1) as controllersecondary,
        ):
            async with watcher.Model(domain=controllerprimary.domain, config=watcher_config) as model:
                await controllerprimary.tel_agcGenset150.set_write(mainFailure=False, force_output=True)
                await controllersecondary.tel_agcGenset150.set_write(mainFailure=False, force_output=True)

                await asyncio.sleep(STD_TIMEOUT)

                await model.enable()

                assert len(model.rules) == 1
                rule_name = "ESS.PowerGeneratorFail"
                rule = model.rules[rule_name]
                rule.alarm.init_severity_queue()

                def calculate_expected_severity(primary_failure, secondary_failure):
                    if not primary_failure and not secondary_failure:
                        return AlarmSeverity.NONE
                    elif (primary_failure and not secondary_failure) or (
                        not primary_failure and secondary_failure
                    ):
                        return AlarmSeverity.SERIOUS
                    elif primary_failure and secondary_failure:
                        return AlarmSeverity.CRITICAL

                for failure_state_primary, failure_state_secondary in (
                    (True, False),
                    (False, True),
                    (True, True),
                    (False, False),
                ):
                    initial_failure_state_primary = controllerprimary.tel_agcGenset150.data.mainFailure
                    initial_failure_state_secondary = controllersecondary.tel_agcGenset150.data.mainFailure

                    await controllerprimary.tel_agcGenset150.set_write(
                        mainFailure=failure_state_primary, force_output=True
                    )

                    if initial_failure_state_primary != failure_state_primary:
                        severity = await asyncio.wait_for(
                            rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT
                        )

                        expected_severity = calculate_expected_severity(
                            controllerprimary.tel_agcGenset150.data.mainFailure,
                            controllersecondary.tel_agcGenset150.data.mainFailure,
                        )

                        assert severity == expected_severity
                        assert rule.alarm.severity_queue.empty()

                    await controllersecondary.tel_agcGenset150.set_write(
                        mainFailure=failure_state_secondary, force_output=True
                    )

                    if initial_failure_state_secondary != failure_state_secondary:
                        severity = await asyncio.wait_for(
                            rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT
                        )

                        expected_severity = calculate_expected_severity(
                            controllerprimary.tel_agcGenset150.data.mainFailure,
                            controllersecondary.tel_agcGenset150.data.mainFailure,
                        )

                        assert severity == expected_severity
                        assert rule.alarm.severity_queue.empty()
