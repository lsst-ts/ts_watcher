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
import math
import pathlib
import types
import unittest
from unittest import mock

import yaml
from lsst.ts import salobj, utils, watcher
from lsst.ts.watcher.rules import PowerOutage
from lsst.ts.xml.enums.Watcher import AlarmSeverity

index_gen = utils.index_generator()
STD_TIMEOUT = 5  # Max time to send/receive a topic (seconds)


class PowerOutageTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()
        self.index = next(index_gen)
        self.configpath = (
            pathlib.Path(__file__).resolve().parent.parent
            / "data"
            / "config"
            / "rules"
            / "power_outage"
        )
        self.curr_tai = 630720100.0

    def current_tai(self):
        """Wrapper function to mock lsst.ts.utils.current_tai."""
        return self.curr_tai

    def get_config(self, filepath):
        with open(filepath, "r") as f:
            config_dict = yaml.safe_load(f)
        return PowerOutage.make_config(**config_dict)

    async def test_validation(self):
        for filepath in self.configpath.glob("good_*.yaml"):
            with self.subTest(filepath=filepath):
                config = self.get_config(filepath=filepath)
                assert isinstance(config, types.SimpleNamespace)

    async def test_constructor(self):
        config = self.get_config(filepath=self.configpath / "good_full.yaml")
        rule = PowerOutage(config=config)
        assert len(rule.remote_info_list) == 2
        expected_sal_index = 301
        for i, remote_info in enumerate(rule.remote_info_list):
            assert remote_info.name == "EPM"
            assert remote_info.index == expected_sal_index

    async def test_operation(self):
        rule_config_path = self.configpath / "good_full.yaml"
        with open(rule_config_path, "r") as f:
            rule_config_dict = yaml.safe_load(f)
        watcher_config_dict = dict(
            disabled_sal_components=[],
            auto_acknowledge_delay=3600,
            auto_unacknowledge_delay=3600,
            rules=[dict(classname="PowerOutage", configs=[rule_config_dict])],
            escalation=(),
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)
        with mock.patch(
            "lsst.ts.watcher.rules.power_outage.utils.current_tai", self.current_tai
        ):
            async with salobj.Controller(
                name="EPM", index=301
            ) as controller, watcher.Model(
                domain=controller.domain, config=watcher_config
            ) as model:
                test_data_items = [
                    {
                        "topic": controller.tel_xups,
                        "is_power_outage": False,
                        "expected_severity": AlarmSeverity.NONE,
                    },
                    {
                        "topic": controller.tel_xups,
                        "is_power_outage": True,
                        "expected_severity": AlarmSeverity.WARNING,
                    },
                    {
                        "topic": controller.tel_xups,
                        "is_power_outage": True,
                        "expected_severity": AlarmSeverity.CRITICAL,
                    },
                    {
                        "topic": controller.tel_scheiderPm5xxx,
                        "is_power_outage": False,
                        "expected_severity": AlarmSeverity.NONE,
                    },
                    {
                        "topic": controller.tel_scheiderPm5xxx,
                        "is_power_outage": True,
                        "expected_severity": AlarmSeverity.NONE,
                    },
                    {
                        "topic": controller.tel_scheiderPm5xxx,
                        "is_power_outage": True,
                        "expected_severity": AlarmSeverity.NONE,
                    },
                    {
                        "topic": controller.tel_scheiderPm5xxx,
                        "is_power_outage": True,
                        "expected_severity": AlarmSeverity.WARNING,
                    },
                ]

                rule_name = "PowerOutage.EPM:301"
                rule = model.rules[rule_name]
                rule.alarm.init_severity_queue()

                await model.enable()

                num_zeros_schneider = 0
                for index, data_item in enumerate(test_data_items):
                    if index == 2:
                        self.curr_tai += (
                            watcher_config.rules[0]["configs"][0][
                                "generator_startup_time"
                            ]
                            + 1.0
                        )
                    await self.send_epm_data(
                        model=model,
                        topic=data_item["topic"],
                        is_power_outage=data_item["is_power_outage"],
                    )
                    if hasattr(data_item["topic"].data, "activePowerA"):
                        if data_item["is_power_outage"]:
                            num_zeros_schneider += 1
                        else:
                            num_zeros_schneider = 0
                    if num_zeros_schneider == 0 or num_zeros_schneider >= 3:
                        severity = await asyncio.wait_for(
                            rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT
                        )
                        assert severity == data_item["expected_severity"]
                    assert rule.alarm.severity_queue.empty()

    async def send_epm_data(
        self,
        model,
        topic,
        is_power_outage,
    ):
        """Send EPM data and wait for the rule to be triggered.

        Parameters
        ----------
        model : `watcher.Model`
            Watcher model.
        topic : `lsst.ts.salobj.topics.WriteTopic`
            the controller topic that writes the power telemetry.
        is_power_outage : `bool`
            If True then mock a power outage.
        """

        telemetry: dict[str, float] = {}
        if hasattr(topic.data, "activePowerA"):
            # Schneider UPS.
            value = 45.0 if not is_power_outage else 0.0
            telemetry = {
                "activePowerA": value,
                "activePowerB": value,
                "activePowerC": value,
            }
        elif hasattr(topic.data, "inputPower"):
            # Eaton XUPS.
            value = 45.0 if not is_power_outage else math.nan
            telemetry = {"inputPower": [value, value, value]}

        await watcher.write_and_wait(
            model=model,
            topic=topic,
            **telemetry,
        )
