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

# from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts import salobj
from lsst.ts import watcher

STD_TIMEOUT = 5  # Max time to send/receive a topic (seconds)


class CpVerifyTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()

    def make_config(self, calibration_type, ocps_index, verification_threshold):
        """Make a config for the Cp Verify rule.

        Parameters
        ----------
        calibration_type : `str`
            Alarm calibration type: BIAS, DARK, or FLAT.
        ocps_index : `int`
            OCPS index (e.g., OCPS:1: LATISS; OCPS:2: LSSTComCam).
        verification_threshold: `int`
            Maximum number of failures per detector per test type
            in `base_make_calibrations.py` after runnign `cp_verify`.
        """
        schema = watcher.rules.CpVerifyAlarm.get_schema()
        validator = salobj.DefaultingValidator(schema)
        config_dict = dict(calibration_type=calibration_type,
                           ocps_index=ocps_index,
                           verification_threshold=verification_threshold
                           )
        full_config_dict = validator.validate(config_dict)
        config = types.SimpleNamespace(**full_config_dict)
        for key in config_dict:
            assert getattr(config, key) == config_dict[key]
        return config

    async def test_basics(self):
        schema = watcher.rules.CpVerifyAlarm.get_schema()
        assert schema is not None
        name = "OCPS"
        calibration_type = 'BIAS'
        verification_threshold = 8
        # OCPS index 1: LATISS
        ocps_index = 1
        desired_rule_name = f"CpVerifyAlarm.{ocps_index}.{name}"
        config = self.make_config(calibration_type=calibration_type,
                                  ocps_index=ocps_index,
                                  verification_threshold=verification_threshold)
        rule = watcher.rules.CpVerifyAlarm(config=config)
        assert rule.name == desired_rule_name
        assert isinstance(rule.alarm, watcher.Alarm)
        assert rule.alarm.name == rule.name
        assert rule.alarm.nominal
        assert len(rule.remote_info_list) == 1
        remote_info = rule.remote_info_list[0]
        assert remote_info.name == name
        assert remote_info.index == 0
        assert name in repr(rule)
        assert "CpVerifyAlarm" in repr(rule)

    async def test_call(self):
        calib_type = "BIAS"
        name = "OCPS"
        ocps_index = 1

        watcher_config_dict = yaml.safe_load(
            f"""
            disabled_sal_components: []
            auto_acknowledge_delay: 3600
            auto_unacknowledge_delay: 3600
            rules:
            - classname: CpVerifyAlarm
              configs:
              - calibration_type: {calib_type}
              - ocps_index: {ocps_index}
            escalation: []
            """
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)
        # use mock OCPS response and verify data below to test
        # self.check_response(response, verify_stats) in the alarm

        async with salobj.Controller(name="OCPS", index=ocps_index) as ocps:
            async with watcher.Model(
                domain=ocps.domain, config=watcher_config
            ) as model:
                model.enable()

                assert len(model.rules) == 1
                rule_name = f"cpVerifyAlarm:{ocps_index}.{name}"
                rule = model.rules[rule_name]
                rule.alarm.init_severity_queue()

                for test_params in self.get_test_params():
                    response_verify = await self.mock_latiss_ocps_response()

                    await ocps.evt_job_result.set_write(
                        result=response_verify,
                    )

                    # This will publish 2 alarm states for each set of test
                    # parameters: one for the queue ScriptQueue event, the next
                    # for the script ScriptQueue event.
                    for expected_severity in test_params.expected_severity:
                        with self.subTest(
                            description=test_params.description,
                            expected_severity=expected_severity,
                        ):
                            severity = await asyncio.wait_for(
                                rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT
                            )

                            assert severity == expected_severity
                    assert rule.alarm.severity_queue.empty()

    async def mock_latiss_ocps_response(self):
        """Return example of cp_verify bias OCPS response.

        Returns
        -------
        response_verify : `dict`
            Dictionary with OCPS cp_verify bias response for LATISS.
        """
        with open("./data/cp_verify_alarm/ocps_bias_verify_response.yaml", "r") as f:
            response_verify = yaml.load(f, Loader=yaml.CLoader)

        return response_verify

    async def mock_verify_stats_bias(self):
        """Return example of cp_verify bias statistics for LATISS.

        Returns
        -------
        verify_stats_bias : `dict`
            Dictionary with cp_verify bias statistics for LATISS.

        Notes
        -----
        verifyCollection = 'u/ocps/ff28c3e10f9f4d64b87533d9f1299a31'
        butler = dB.Butler("/repo/LATISS/", collections=[verifyCollection])
        verify_stats_bias = butler.get('verifyBiasStats', instrument='LATISS')
        """
        with open("./data/cp_verify_alarm/cp_verify_bias_stats.yaml", "r") as f:
            verify_stats_bias = yaml.load(f, Loader=yaml.CLoader)

        return verify_stats_bias
