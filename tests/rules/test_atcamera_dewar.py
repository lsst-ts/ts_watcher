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
import pathlib
import types
import unittest

import jsonschema
import pytest
import yaml
from lsst.ts import salobj, utils, watcher
from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts.watcher.rules import ATCameraDewar

# Standard timeout (seconds)
STD_TIMEOUT = 10


class ATCameraDewarTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()
        self.configpath = (
            pathlib.Path(__file__).resolve().parent.parent
            / "data"
            / "config"
            / "rules"
            / "atcamera_dewar"
        )

    def get_config(self, filepath):
        with open(filepath, "r") as f:
            config_dict = yaml.safe_load(f)
        if config_dict is None:
            config_dict = dict()
        return ATCameraDewar.make_config(**config_dict)

    async def test_validation(self):
        for filepath in self.configpath.glob("good_*.yaml"):
            with self.subTest(filepath=filepath):
                config = self.get_config(filepath=filepath)
                assert isinstance(config, types.SimpleNamespace)

        for filepath in self.configpath.glob("bad_*.yaml"):
            with self.subTest(filepath=filepath):
                with pytest.raises(jsonschema.ValidationError):
                    self.get_config(filepath=filepath)

    async def test_constructor(self):
        config = self.get_config(filepath=self.configpath / "good_full.yaml")
        rule = ATCameraDewar(config=config)
        assert len(rule.remote_info_list) == 1
        remote_info = rule.remote_info_list[0]
        assert remote_info.name == "ATCamera"
        assert remote_info.callback_names == ("tel_vacuum",)

        for filepath in self.configpath.glob("invalid_*.yaml"):
            with self.subTest(filepath=filepath):
                config = self.get_config(filepath=filepath)
                with pytest.raises(ValueError):
                    ATCameraDewar(config=config)

    async def test_operation(self):
        rule_config_path = self.configpath / "good_full.yaml"
        with open(rule_config_path, "r") as f:
            rule_config_dict = yaml.safe_load(f)

        watcher_config_dict = dict(
            disabled_sal_components=[],
            auto_acknowledge_delay=3600,
            auto_unacknowledge_delay=3600,
            rules=[dict(classname="ATCameraDewar", configs=[rule_config_dict])],
            escalation=(),
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)
        async with salobj.Controller(name="ATCamera") as controller, watcher.Model(
            domain=controller.domain, config=watcher_config
        ) as model:
            assert len(model.rules) == 1
            rule = list(model.rules.values())[0]
            assert rule.alarm.nominal

            model.enable()

            # Nominal values, based on good_full.yaml,
            # translated to topic field names.
            nominal_data_dict = dict(
                tempCCD=-95,
                tempColdPlate=-140,
                tempCryoHead=-180,
                vacuum=0.5e-6,
            )

            # For each measurement in turn, cycle through all values
            # provided by the threshold handler, ending with a nominal value.
            for name, threshold_handlers in rule.threshold_handlers.items():
                meas_info = rule.name_meas_info[name]
                num_message = rule.config.min_values
                field_name = meas_info.field_name
                data_dict = nominal_data_dict.copy()
                for threshold_handler in threshold_handlers:
                    for (
                        value,
                        expected_severity,
                    ) in threshold_handler.get_test_value_severities():
                        rule.reset_all()
                        data_dict[field_name] = value
                        for i in range(num_message - 1):
                            await watcher.write_and_wait(
                                model=model, topic=controller.tel_vacuum, **data_dict
                            )
                            assert rule.alarm.severity == AlarmSeverity.NONE
                        assert not rule.had_enough_data
                        assert rule.alarm.nominal

                        await watcher.write_and_wait(
                            model=model, topic=controller.tel_vacuum, **data_dict
                        )
                        assert rule.alarm.severity == expected_severity
                        assert rule.had_enough_data

            # Test that seeing no data for max_data_age
            # triggers a SERIOUS alarm.
            short_max_data_age = 0.2
            rule.config.max_data_age = short_max_data_age
            rule.reset_all()
            assert rule.alarm.nominal
            assert rule.alarm.severity == AlarmSeverity.NONE
            # The factor of 1.2 provides some margin
            await asyncio.sleep(short_max_data_age * 1.2)
            assert rule.alarm.severity == AlarmSeverity.SERIOUS
            assert not rule.had_enough_data
            assert not rule.alarm.nominal

    async def test_windowing(self):
        """Test that only data within the specified time window is used.

        This test involves careful timing.
        The margins are intentionally large (making the test slow to run)
        in order to make the test robust. In addition, there are several
        print statements to show just how much margin exists.
        """
        rule_config_path = self.configpath / "good_full.yaml"

        # Publish a batch of bad data. Then wait a bit
        # and publish a batch of good data.
        # Make temperature data expire first, so once temperatures expire
        # (before vacuum expires) the reason will be solely vacuum.
        min_values = 10
        temperature_window = 1.0
        vacuum_window = 2.0
        assert vacuum_window > temperature_window
        with open(rule_config_path, "r") as f:
            rule_config_dict = yaml.safe_load(f)
            rule_config_dict["min_values"] = min_values
            rule_config_dict["temperature_window"] = temperature_window
            rule_config_dict["vacuum_window"] = vacuum_window

        watcher_config_dict = dict(
            disabled_sal_components=[],
            auto_acknowledge_delay=3600,
            auto_unacknowledge_delay=3600,
            rules=[dict(classname="ATCameraDewar", configs=[rule_config_dict])],
            escalation=(),
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)
        async with salobj.Controller(name="ATCamera") as controller, watcher.Model(
            domain=controller.domain, config=watcher_config
        ) as model:
            assert len(model.rules) == 1
            rule = list(model.rules.values())[0]
            assert rule.alarm.nominal

            model.enable()

            # Nominal values, based on good_full.yaml,
            # translated to topic field names.
            nominal_data_dict = dict(
                tempCCD=-95,
                tempColdPlate=-140,
                tempCryoHead=-180,
                vacuum=0.5e-6,
            )

            # Data that will trigger a serious alarm for every measurement
            # based on good_full.yaml,
            # translated to topic field names.
            seriously_bad_data_dict = dict(
                tempCCD=-97.5,
                tempColdPlate=-124.6,
                tempCryoHead=-162.1,
                vacuum=3.5e-6,
            )

            # Publish significantly more bad data than good data,
            # so the median of it all equals the bad values.
            num_bad_message = min_values * 2
            num_good_message = min_values

            for i in range(num_bad_message):
                num_values = i + 1
                await watcher.write_and_wait(
                    model=model, topic=controller.tel_vacuum, **seriously_bad_data_dict
                )
                should_have_enough_data = num_values >= min_values
                if should_have_enough_data:
                    expected_severity = AlarmSeverity.SERIOUS
                else:
                    expected_severity = AlarmSeverity.NONE
                assert rule.alarm.severity == expected_severity
                assert rule.had_enough_data == should_have_enough_data
            bad_end_timestamp = controller.tel_vacuum.data.private_sndStamp

            assert rule.had_enough_data
            assert rule.alarm.severity == AlarmSeverity.SERIOUS
            for name, meas_info in rule.name_meas_info.items():
                assert meas_info.descr in rule.alarm.reason

            bad_temperature_expiry_tai = bad_end_timestamp + temperature_window
            bad_vacuum_expiry_tai = bad_end_timestamp + vacuum_window

            # Sleep a bit to give a gap between the bad data and the good data.
            gap_duration = 0.5
            gap_end_tai = utils.current_tai() + gap_duration
            gap_margin = bad_temperature_expiry_tai - gap_end_tai
            print(f"gap margin={gap_margin:0.2f} seconds; must be > 0")
            assert gap_margin > 0
            await asyncio.sleep(gap_duration)

            # At this point no data should have expired
            # so all measurements should be reporting serious alarms
            # (despite the mix of bad data and nominal data, because
            # the rule uses median and there is more bad data).
            for i in range(num_good_message):
                await watcher.write_and_wait(
                    model=model, topic=controller.tel_vacuum, **nominal_data_dict
                )
                assert rule.alarm.severity == AlarmSeverity.SERIOUS
            temperature_expiry_duration = (
                bad_temperature_expiry_tai + 0.1 - utils.current_tai()
            )
            print(
                f"temperature_expiry_duration={temperature_expiry_duration:0.2f}; must be > 0"
            )
            assert temperature_expiry_duration > 0
            assert rule.had_enough_data
            assert rule.alarm.severity == AlarmSeverity.SERIOUS
            for name, meas_info in rule.name_meas_info.items():
                assert meas_info.descr in rule.alarm.reason

            # Wait for the bad temperature data to expire
            await asyncio.sleep(temperature_expiry_duration)

            # At this point the temperature data should have expired
            # but the vacuum data should not.
            # We have to put data to see the effects of that expiration.
            await watcher.write_and_wait(
                model=model, topic=controller.tel_vacuum, **nominal_data_dict
            )
            assert rule.alarm.severity == AlarmSeverity.SERIOUS

            vacuum_expiry_duration = bad_vacuum_expiry_tai > utils.current_tai()
            print(f"vacuum_expiry_duration={vacuum_expiry_duration:0.2f}; must be >0")
            assert vacuum_expiry_duration > 0, (
                f"vacuum_expiry_duration={vacuum_expiry_duration} <= 0; "
                "test is running too slowly to work"
            )
            assert rule.had_enough_data
            assert rule.alarm.severity == AlarmSeverity.SERIOUS
            for meas_info in rule.name_meas_info.values():
                if meas_info.is_temperature:
                    assert meas_info.descr not in rule.alarm.reason
                else:
                    assert meas_info.descr in rule.alarm.reason

            # Wait for the vacuum data to expire
            await asyncio.sleep(vacuum_expiry_duration + 0.1)

            # At this point all bad data should have expired
            # We have to put data to see the effects of that expiration.
            await watcher.write_and_wait(
                model=model, topic=controller.tel_vacuum, **nominal_data_dict
            )
            assert rule.alarm.severity == AlarmSeverity.NONE
