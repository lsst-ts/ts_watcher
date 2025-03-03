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
import contextlib
import types
import unittest

import jsonschema
import pytest
import yaml
from lsst.ts import salobj, watcher
from lsst.ts.xml.enums.Watcher import AlarmSeverity


class TelemetryTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        if hasattr(salobj, "set_random_topic_subname"):
            salobj.set_random_topic_subname()
        else:
            salobj.set_random_lsst_dds_partition_prefix()

    async def test_basics(self):
        schema = watcher.rules.Telemetry.get_schema()
        assert schema is not None
        name = "MTDome"
        callback_name = "tel_azimuth"
        timeout = 1.2
        config = watcher.rules.Telemetry.make_config(
            name=name,
            callback_name=callback_name,
            summary_states=["DISABLED", "ENABLED"],
            timeout=timeout,
            alarm_severity=3,
        )
        desired_rule_name = f"Telemetry.{name}:0"

        rule = watcher.rules.Telemetry(config=config)
        assert rule.name == desired_rule_name
        assert isinstance(rule.alarm, watcher.Alarm)
        assert rule.alarm.name == rule.name
        assert rule.alarm.nominal
        assert len(rule.remote_info_list) == 2
        remote_info = rule.remote_info_list[0]
        assert remote_info.name == name
        assert remote_info.index == 0
        assert name in repr(rule)
        assert "Telemetry" in repr(rule)

    def test_config_validation(self):
        # Check defaults
        minimal_config_dict = dict(name="MTDome", callback_name="tel_azimuth")
        minimal_config = watcher.rules.Telemetry.make_config(**minimal_config_dict)
        assert minimal_config.name == minimal_config_dict["name"]
        assert minimal_config.timeout == 15
        assert minimal_config.alarm_severity == AlarmSeverity.CRITICAL

        # Check all values specified
        good_config_dict = dict(
            name="MTDome",
            callback_name="tel_azimuth",
            summary_states=["DISABLED", "ENABLED"],
            timeout=1,
            alarm_severity=AlarmSeverity.SERIOUS,
        )
        good_config = watcher.rules.Telemetry.make_config(**good_config_dict)
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
                watcher.rules.Telemetry.make_config(**bad_config_dict)

    async def test_operation(self):
        name = "MTDome"
        callback_name = "tel_azimuth"
        index = 0
        timeout = 2.0
        alarm_severity = AlarmSeverity.CRITICAL

        watcher_config_dict = yaml.safe_load(
            f"""
            disabled_sal_components: []
            auto_acknowledge_delay: 3600
            auto_unacknowledge_delay: 3600
            rules:
            - classname: Telemetry
              configs:
              - name: {name}:{index}
                callback_name: {callback_name}
                summary_states: ["DISABLED", "ENABLED"]
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
                rule_name = f"Telemetry.{name}:{index}"
                rule = model.rules[rule_name]
                alarm = rule.alarm
                alarm.init_severity_queue()

                # Start a Telemetry loop and check severity=None.
                async with self.telemetry_loop(controller=controller):
                    await alarm.assert_next_severity(AlarmSeverity.NONE)
                    assert alarm.nominal

                    # Make sure alarm is not republished
                    with pytest.raises(asyncio.TimeoutError):
                        await alarm.assert_next_severity(AlarmSeverity.NONE)
                    assert alarm.nominal

                # With the Telemetry loop closed again no alarm should be
                # raised since the CSC is in STANDBY.
                with pytest.raises(asyncio.TimeoutError):
                    await alarm.assert_next_severity(AlarmSeverity.NONE)
                assert alarm.nominal

                # Send the DISABLED state event.
                await self._publish_disabled_event(controller)

                # Now wait until the alarm occurs.
                await alarm.assert_next_severity(alarm_severity, timeout=timeout * 2.5)
                assert not alarm.nominal
                assert alarm.max_severity == alarm_severity

                # Make sure alarm is not republished
                with pytest.raises(asyncio.TimeoutError):
                    await alarm.assert_next_severity(
                        alarm_severity, timeout=timeout * 2.5
                    )

                # Start Telemetry loop again event and check that severity is
                # None but that max_severity is still high (since the alarm
                # has not been acknowledged).
                alarm.flush_severity_queue()
                async with self.telemetry_loop(controller=controller):
                    await alarm.assert_next_severity(AlarmSeverity.NONE)
                    assert not alarm.nominal
                    assert alarm.max_severity == alarm_severity

                    # Make sure alarm is not republished
                    with pytest.raises(asyncio.TimeoutError):
                        await alarm.assert_next_severity(AlarmSeverity.NONE)
                    assert not alarm.nominal
                    assert alarm.max_severity == alarm_severity

                    # acknowledge alarm
                    await alarm.acknowledge(severity=alarm_severity, user="some_user")
                    # alarm severity should not change, but alarm is now
                    # nominal
                    with pytest.raises(asyncio.TimeoutError):
                        await alarm.assert_next_severity(AlarmSeverity.NONE)
                    assert alarm.nominal
                    assert alarm.max_severity == AlarmSeverity.NONE

    @contextlib.asynccontextmanager
    async def telemetry_loop(self, controller):
        try:
            _task = asyncio.create_task(self._publish_azimuth_telemetry(controller))
            yield
            _task.cancel()
            await _task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Exception in telemetry loop: {e!r}")
            raise

    @staticmethod
    async def _publish_azimuth_telemetry(controller):
        while True:
            await controller.tel_azimuth.write()
            await asyncio.sleep(1.0)

    async def _publish_disabled_event(self, controller):
        await controller.evt_summaryState.set_write(summaryState=salobj.State.DISABLED)
