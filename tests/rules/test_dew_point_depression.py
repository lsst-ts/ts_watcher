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
import functools
import math
import pathlib
import types
import unittest

import jsonschema
import numpy.random
import pytest
import yaml
from lsst.ts import salobj, utils, watcher
from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts.watcher.rules import DewPointDepression

index_gen = utils.index_generator()


class DewPointDepressionTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()
        self.index = next(index_gen)
        self.configpath = (
            pathlib.Path(__file__).resolve().parent.parent
            / "data"
            / "config"
            / "rules"
            / "dew_point_depression"
        )
        # Number of values to set to real temperatures; the rest are NaN.
        self.num_valid_temperatures = 12

    def get_config(self, filepath):
        """Read a config file and return the validated config.

        Parameters
        ----------
        filepath : `pathlib.Path` or `str`
            Full path to config file.
        """
        with open(filepath, "r") as f:
            config_dict = yaml.safe_load(f)
        return DewPointDepression.make_config(**config_dict)

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
        rule = DewPointDepression(config=config)
        assert len(rule.remote_info_list) == 2
        expected_sal_indices = (1, 5)
        expected_poll_names = [
            ("tel_temperature", "tel_dewPoint"),
            ("tel_dewPoint",),
        ]
        for i, remote_info in enumerate(rule.remote_info_list):
            assert remote_info.name == "ESS"
            assert remote_info.index == expected_sal_indices[i]
            assert remote_info.poll_names == expected_poll_names[i]

    async def test_operation(self):
        poll_interval = 0.05
        max_data_age = poll_interval * 10
        rule_config_path = self.configpath / "good_full.yaml"
        with open(rule_config_path, "r") as f:
            rule_config_dict = yaml.safe_load(f)
            rule_config_dict["poll_interval"] = poll_interval
            rule_config_dict["max_data_age"] = max_data_age

        watcher_config_dict = dict(
            disabled_sal_components=[],
            auto_acknowledge_delay=3600,
            auto_unacknowledge_delay=3600,
            rules=[dict(classname="DewPointDepression", configs=[rule_config_dict])],
            escalation=(),
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)
        async with salobj.Controller(
            name="ESS", index=1
        ) as controller1, salobj.Controller(
            name="ESS", index=5
        ) as controller5, watcher.Model(
            domain=controller1.domain, config=watcher_config
        ) as model:
            assert len(model.rules) == 1
            rule = list(model.rules.values())[0]
            rule.alarm.init_severity_queue()
            assert rule.alarm.nominal

            await model.enable()

            # Dicts of sensor name: write topic.
            # The content must match the rule configuration.
            dew_point_topics = dict(
                high=controller5.tel_dewPoint,
                low=controller5.tel_dewPoint,
                outside=controller5.tel_dewPoint,
                inside=controller1.tel_dewPoint,
            )
            temperature_topics = dict(
                maintel=(controller1.tel_temperature, None),
                auxtel=(controller1.tel_temperature, (0, 2, 1, 3)),
            )

            send_ess_data = functools.partial(
                self.send_ess_data,
                model=model,
                rule=rule,
                dew_point_topics=dew_point_topics,
                temperature_topics=temperature_topics,
            )

            # Stop the rule polling task and poll manually.
            rule.stop()

            # Send data indicating condensation using filter values
            # other than those the rule is listening to.
            # This should not affect the rule.
            await send_ess_data(dew_point_depression=-1, use_other_filter_values=True)
            rule.poll_start_tai = utils.current_tai()
            await rule.update_alarm_severity()
            assert rule.alarm.severity == AlarmSeverity.NONE
            assert rule.alarm.nominal

            # Check a sequence of dew points
            for (
                dew_point_depression,
                expected_severity,
            ) in rule.threshold_handler.get_test_value_severities():
                await send_ess_data(dew_point_depression=dew_point_depression)
                await rule.update_alarm_severity()
                assert rule.alarm.severity == expected_severity

            # Check that no data for max_data_age triggers severity=SERIOUS.
            # Resume polling first.
            rule.start()
            rule.alarm.flush_severity_queue()
            assert rule.alarm.severity != AlarmSeverity.SERIOUS
            await asyncio.sleep(max_data_age + poll_interval * 2)
            await rule.alarm.assert_next_severity(
                AlarmSeverity.SERIOUS, flush=False, check_empty=False
            )
            # should not be published again
            with pytest.raises(asyncio.TimeoutError):
                await rule.alarm.assert_next_severity(AlarmSeverity.SERIOUS, flush=True)

    async def send_ess_data(
        self,
        dew_point_depression,
        model,
        rule,
        dew_point_topics,
        temperature_topics,
        use_other_filter_values=False,
        verbose=False,
    ):
        """Send ESS data.

        The dew_point_depression argument changes the published temperatures
        but NOT the values published by the dew point sensors.
        This avoids a race condition between the polling loop in the rule
        and publishing the data.

        Parameters
        ----------
        dew_point_depression : `float`
            Desired pessimistic dew point depression
        model : `Model`
            Watcher model.
        rule : `DewPointDepressionRule`
            Dew point depression rule.
        dew_point_topics : `dict` of ``str`: write topic
            Dict of filter_value: controller topic that writes dew point.
        temperature_topics : `dict` of `str`: (write topic, indices)
            Dict of filter_value: (controller topic, indices)
            where the topic writes temperature, and indices indicates
            which indices to write (None for all of them).
        use_other_filter_values : `bool`, optional
            If True then send data for other filter values than those read by
            the rule. The rule should ignore this data.
        verbose : `bool`, optional
            If True then print the data sent.

        Notes
        -----
        Write pessimistic data to one dew point topic (higher than normal
        dew point) and to one temperature channel (lower than normal
        temperature), and normal data to the remaining topics, such that:
        pessimistic temperature - pessimistic dew point = dew_point_depression.

        The topics and (for temperature) channel for the pessimistic data
        are randomly chosen. This helps ensure that the rule uses the
        most pessimistic data from any sensor.
        """
        if verbose:
            print(
                f"send_ess_data(dew_point_depression={dew_point_depression}, "
                f"use_other_filter_values={use_other_filter_values}"
            )

        # delta temperature is used as follows:
        # * temperature: regular temperature = delta + lowest temperature
        # * dew point: regular dew point is computed using dew point - delta
        #   air temperature - delta
        delta_temperature = 2

        pessimistic_air_temperature = 10

        pessimistic_dew_point = pessimistic_air_temperature - dew_point_depression
        normal_dew_point = pessimistic_dew_point - delta_temperature
        if verbose:
            print(f"pessimistic_dew_point={pessimistic_dew_point}")
            print(f"normal_dew_point={normal_dew_point}")

        rng = numpy.random.default_rng(seed=314)
        pessimistic_dew_point_filter_value = rng.choice(list(dew_point_topics.keys()))
        for filter_value, topic in dew_point_topics.items():
            if filter_value == pessimistic_dew_point_filter_value:
                dew_point = pessimistic_dew_point
            else:
                dew_point = normal_dew_point
            if use_other_filter_values:
                filter_value += " with modifications"
            await watcher.write_and_wait(
                model=model,
                topic=topic,
                sensorName=filter_value,
                dewPoint=dew_point,
                verbose=verbose,
            )

        pessimistic_temperature = pessimistic_dew_point + dew_point_depression
        normal_temperature = pessimistic_temperature + delta_temperature
        if verbose:
            print(f"pessimistic_temperature={pessimistic_temperature}")
            print(f"normal_temperature={normal_temperature}")

        pessimistic_temperature_filter_value = rng.choice(
            list(temperature_topics.keys())
        )
        for filter_value, (topic, indices) in temperature_topics.items():
            num_temperatures = len(topic.data.temperature)
            assert self.num_valid_temperatures < num_temperatures
            num_nans = num_temperatures - self.num_valid_temperatures
            temperatures = [normal_temperature] * self.num_valid_temperatures + [
                math.nan
            ] * num_nans
            if filter_value == pessimistic_temperature_filter_value:
                if indices is None:
                    pessimistic_index = rng.choice(range(self.num_valid_temperatures))
                else:
                    pessimistic_index = rng.choice(indices)
                temperatures[pessimistic_index] = pessimistic_temperature
            if use_other_filter_values:
                filter_value += " with modifications"
            await watcher.write_and_wait(
                model=model,
                topic=topic,
                sensorName=filter_value,
                temperature=temperatures,
                verbose=verbose,
            )
