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
import pytest
import types
import unittest

import jsonschema
import numpy.random
import yaml

from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts import salobj
from lsst.ts import utils
from lsst.ts import watcher
from lsst.ts.watcher.rules import OverTemperature

index_gen = utils.index_generator()


class OverTemperatureTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()
        self.index = next(index_gen)
        self.configpath = (
            pathlib.Path(__file__).resolve().parent.parent
            / "data"
            / "config"
            / "rules"
            / "over_temperature"
        )
        # Number of values to set to real temperatures; the rest are NaN.
        self.num_valid_temperatures = 12

    def get_config(self, filepath):
        schema = OverTemperature.get_schema()
        validator = salobj.DefaultingValidator(schema)
        with open(filepath, "r") as f:
            config_dict = yaml.safe_load(f)
        full_config_dict = validator.validate(config_dict)
        config = types.SimpleNamespace(**full_config_dict)
        for key in config_dict:
            assert getattr(config, key) == config_dict[key]
        return config

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
        rule = OverTemperature(config=config)
        assert len(rule.remote_info_list) == 2
        expected_sal_indices = (1, 5)
        expected_poll_names = [
            ("tel_temperature",),
            ("tel_temperature",),
        ]
        for i, remote_info in enumerate(rule.remote_info_list):
            assert remote_info.name == "ESS"
            assert remote_info.index == expected_sal_indices[i]
            assert remote_info.poll_names == expected_poll_names[i]

    async def test_operation(self):
        poll_interval = 0.05
        max_data_age = poll_interval * 5
        rule_config_path = self.configpath / "good_full.yaml"
        with open(rule_config_path, "r") as f:
            rule_config_dict = yaml.safe_load(f)
            rule_config_dict["poll_interval"] = poll_interval
            rule_config_dict["max_data_age"] = max_data_age

        watcher_config_dict = dict(
            disabled_sal_components=[],
            auto_acknowledge_delay=3600,
            auto_unacknowledge_delay=3600,
            rules=[dict(classname="OverTemperature", configs=[rule_config_dict])],
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

            model.enable()

            # The keys are based on the rule configuration
            temperature_topics = dict(
                upstairs=(controller1.tel_temperature, None),
                downstairs=(controller1.tel_temperature, [0, 2, 1, 3]),
                inside=(controller5.tel_temperature, None),
            )

            send_ess_data = functools.partial(
                self.send_ess_data,
                model=model,
                rule=rule,
                temperature_topics=temperature_topics,
                verbose=False,
            )

            # Stop the rule polling task and poll manually.
            rule.stop()

            # Send data indicating high temperature using filter values
            # other than those the rule is listening to.
            # This should not affect the rule.
            await send_ess_data(temperature=100, use_other_filter_values=True)
            # Give the rule time to deal with all of the new data.
            await asyncio.sleep(poll_interval)
            severity, reason = await rule.poll_once(set_poll_start_tai=True)
            assert severity == AlarmSeverity.NONE
            assert rule.alarm.nominal

            # Check a sequence of temperatures
            for (
                temperature,
                expected_severity,
            ) in rule.threshold_handler.get_test_value_severities():
                await send_ess_data(temperature=temperature)
                severity, reason = await rule.poll_once(set_poll_start_tai=True)
                assert severity == expected_severity

            # Check that no data for max_data_age triggers severity=SERIOUS.
            rule.start()
            assert rule.alarm.severity != AlarmSeverity.SERIOUS
            await asyncio.sleep(max_data_age + poll_interval * 2)
            await rule.alarm.assert_next_severity(AlarmSeverity.SERIOUS, flush=True)

    async def send_ess_data(
        self,
        temperature,
        model,
        rule,
        temperature_topics,
        use_other_filter_values=False,
        verbose=False,
    ):
        """Send ESS data.

        Parameters
        ----------
        temperature : `float`
            Desired pessimistic temperature
        model : `Model`
            Watcher model.
        rule : `rules.OverTemperature`
            over-temperature rule.
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
        Write pessimistic data to one thermometer, and normal data
        to the remaining thermometers.

        The topics and channel for the pessimistic data are randomly chosen.
        This helps ensure that the rule uses the most pessimistic data
        from any sensor.
        """
        if verbose:
            print(
                f"send_ess_data(temperature={temperature}, "
                f"use_other_filter_values={use_other_filter_values}"
            )

        delta_temperature = 2
        pessimistic_temperature = temperature
        normal_temperature = pessimistic_temperature - delta_temperature
        if verbose:
            print(f"pessimistic_temperature={pessimistic_temperature}")
            print(f"normal_temperature={normal_temperature}")

        rng = numpy.random.default_rng(seed=314)
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
