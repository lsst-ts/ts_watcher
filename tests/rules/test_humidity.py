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
import pathlib
import pytest
import types
import unittest

import jsonschema
import numpy.random
import yaml

from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts import salobj
from lsst.ts import watcher
from lsst.ts.watcher.rules import Humidity

index_gen = salobj.index_generator()


class HumidityTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()
        self.index = next(index_gen)
        self.configpath = (
            pathlib.Path(__file__).resolve().parent.parent
            / "data"
            / "config"
            / "humidity"
        )
        # Number of values to set to real temperatures; the rest are NaN.
        self.num_valid_temperatures = 12

    def get_config(self, filepath):
        schema = Humidity.get_schema()
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
            config = self.get_config(filepath=filepath)
            assert isinstance(config, types.SimpleNamespace)

        for filepath in self.configpath.glob("bad_*.yaml"):
            with pytest.raises(jsonschema.ValidationError):
                self.get_config(filepath=filepath)

    async def test_constructor(self):
        config = self.get_config(filepath=self.configpath / "good_full.yaml")
        rule = Humidity(config=config)
        assert len(rule.remote_info_list) == 2
        expected_sal_indices = (5, 1)
        expected_poll_names = [
            ("tel_hx85a", "tel_hx85ba"),
            ("tel_hx85a",),
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
            rules=[dict(classname="Humidity", configs=[rule_config_dict])],
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
            assert rule.alarm.nominal

            model.enable()

            # The keys are based on the rule configuration
            humidity_topics = dict(
                high=controller5.tel_hx85a,
                low=controller5.tel_hx85a,
                outside=controller5.tel_hx85ba,
                inside=controller1.tel_hx85a,
            )

            send_ess_data = functools.partial(
                self.send_ess_data,
                rule=rule,
                humidity_topics=humidity_topics,
                verbose=False,
            )

            # Send data indicating condensation using filter values
            # other than those the rule is listening to.
            # This should not affect the rule.
            await send_ess_data(humidity=100, use_other_filter_values=True)
            assert rule.alarm.nominal

            # Check a sequence of dew points
            hysteresis = rule.config.hysteresis
            warning_level = rule.config.warning_level
            serious_level = rule.config.serious_level
            assert hysteresis > 0
            epsilon = 0.1 * hysteresis
            assert warning_level < serious_level - hysteresis - epsilon

            for humidity, expected_severity in [
                # Just below warning level
                (warning_level - epsilon, AlarmSeverity.NONE),
                # Just below warning level
                (warning_level + epsilon, AlarmSeverity.WARNING),
                # Still in hysteresis range
                (warning_level - hysteresis + epsilon, AlarmSeverity.WARNING),
                # Below hysteresis range
                (warning_level - hysteresis - epsilon, AlarmSeverity.NONE),
                # Just below the serious level
                (serious_level - epsilon, AlarmSeverity.WARNING),
                # Just above serious level
                (serious_level + epsilon, AlarmSeverity.SERIOUS),
                # Still in hysteresis range
                (serious_level - hysteresis + epsilon, AlarmSeverity.SERIOUS),
                # Juat below hysteresis range
                (serious_level - hysteresis - epsilon, AlarmSeverity.WARNING),
                # Just below warning + hysteresis: back to normal
                (warning_level - hysteresis - epsilon, AlarmSeverity.NONE),
            ]:
                await send_ess_data(humidity=humidity)
                await asyncio.sleep(poll_interval * 2.1)
                assert rule.alarm.severity == expected_severity

            await asyncio.sleep(max_data_age + poll_interval * 2.1)
            assert rule.alarm.severity == AlarmSeverity.SERIOUS

    async def send_ess_data(
        self,
        humidity,
        rule,
        humidity_topics,
        use_other_filter_values=False,
        verbose=False,
    ):
        """Send ESS data.

        Parameters
        ----------
        humidity : `float`
            Desired humidity
        rule : `HumidityRule`
            Dew point depression rule.
        humidity_topics : `dict` of ``str`: write topic
            Dict of filter_value: controller topic
            that writes dew point or humidity
        use_other_filter_values : `bool`, optional
            If True then send data for other filter values than those read by
            the rule. The rule should ignore this data.
        verbose : `bool`, optional
            If True then print the data sent.

        Notes
        -----
        Write the specified humidity to one humidity topic,
        and less pessimistic data to the remaining topics.

        The topic is randomly chosen.
        This helps ensure that the rule uses the most pessimistic data
        from any sensor.
        """
        if verbose:
            print(
                f"send_ess_data(humidity={humidity}, "
                f"use_other_filter_values={use_other_filter_values}"
            )

        delta_humidity = 2
        pessimistic_humidity = humidity
        normal_humidity = humidity - delta_humidity
        if verbose:
            print(f"pessimistic_humidity={pessimistic_humidity}")
            print(f"normal_humidity={normal_humidity}")

        rng = numpy.random.default_rng(seed=314)
        pessimistic_humidity_filter_value = rng.choice(list(humidity_topics.keys()))
        for filter_value, topic in humidity_topics.items():
            if filter_value == pessimistic_humidity_filter_value:
                data_dict = dict(
                    relativeHumidity=pessimistic_humidity,
                )
            else:
                data_dict = dict(
                    relativeHumidity=normal_humidity,
                )
            if use_other_filter_values:
                filter_value += " with modifications"
            if verbose:
                print(
                    f"{topic.salinfo.name_index}.{topic.attr_name}.set_put"
                    f"(sensorName={filter_value!r}, {data_dict})"
                )
            topic.set_put(sensorName=filter_value, **data_dict)
            await asyncio.sleep(0.001)