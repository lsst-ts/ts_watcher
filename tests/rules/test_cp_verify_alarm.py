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

# import asyncio
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

    def make_config(self, name):
        """Make a config for the Cp Verify rule.

        Parameters
        ----------
        name : `str`
            CSC name and index in the form `name` or `name:index`.
            The default index is 0.
        """
        schema = watcher.rules.CpVerifyAlarm.get_schema()
        validator = salobj.DefaultingValidator(schema)
        config_dict = dict(name=name)

        full_config_dict = validator.validate(config_dict)
        config = types.SimpleNamespace(**full_config_dict)
        for key in config_dict:
            assert getattr(config, key) == config_dict[key]
        return config

    async def test_basics(self):
        schema = watcher.rules.CpVerifyAlarm.get_schema()
        assert schema is not None
        name = "OCPS"
        config = self.make_config(name=name)
        # OCPS index 1: LATISS
        ocps_index = 1
        desired_rule_name = f"CpVerifyAlarm.{ocps_index}.{name}"

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
        calib_type = "OCPS"
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
    

    async def mock_latiss_ocps_response(self):
        response_verify = {'jobId': 'def62fc0cc6645d089edee4eb797e3f1', 'runId': '832761836', 'ownerId': '', 'phase': 'completed', 'creationTime': '2022-09-2915:02:22+00:00', 'startTime': '2022-09-29 15:02:22+00:00', 'endTime':
'2022-09-29 15:05:10+00:00', 'executionDuration': 168.0, 'destruction': None,
'parameters': {'command': ['/bin/bash', '-c', 'cd $JOB_SOURCE_DIR && bashbin/pipetask.sh'], 'environment': [{'name': 'JOB_SOURCE_DIR', 'value':
'/uws/jobs/def62fc0cc6645d089edee4eb797e3f1/src'}, {'name': 'SRC_GIT_URL',
'value': 'https://github.com/lsst-dm/uws_scripts'}, {'name': 'GIT_COMMIT_REF',
'value': 'main'}, {'name': 'JOB_OUTPUT_DIR', 'value':
'/uws/jobs/def62fc0cc6645d089edee4eb797e3f1/out'}, {'name': 'JOB_ID', 'value':'def62fc0cc6645d089edee4eb797e3f1'}, {'name': 'IMAGE_TAG', 'value': None},
{'name': 'PIPELINE_URL', 'value':
'${CP_PIPE_DIR}/pipelines/Latiss/VerifyBias.yaml'}, {'name': 'BUTLER_REPO', 'value':
'/repo/LATISS'}, {'name': 'RUN_OPTIONS', 'value': '-i LATISS/raw/all -j 8 -i LATISS/calib --register-dataset-types  -c isr:doDefect=False'}, {'name':
'OUTPUT_GLOB', 'value': '*'}, {'name': 'DATA_QUERY', 'value':
"instrument='LATISS' AND detector IN (0) AND exposure IN (2022092900004,2022092900005, 2022092900006, 2022092900007, 2022092900008, 2022092900009,2022092900010, 2022092900011, 2022092900012, 2022092900013, 2022092900014,2022092900015, 2022092900016, 2022092900017, 2022092900018, 2022092900019,2022092900020, 2022092900021, 2022092900022, 2022092900023)"}],
              
}, 'results': [{'id': 24, 'uri': '/uws/jobs/85f23b5af0ba44cf967f183c59b1073e/out/verifyBiasProc_LATISS_empty~holo4_003_AT_O_20220929_000016_RXX_S00_u_ocps_85f23b5af0ba44cf967f183c59b1073e_run.fits'}, {'id': 25, 'uri': '/uws/jobs/85f23b5af0ba44cf967f183c59b1073e/out/verifyBiasProc_LATISS_empty~holo4_003_AT_O_20220929_000015_RXX_S00_u_ocps_85f23b5af0ba44cf967f183c59b1073e_run.fits'},{'id': 26, 'uri': '/uws/jobs/85f23b5af0ba44cf967f183c59b1073e/out/verifyBiasExpStats_LATISS_white_empty~holo4_003_AT_O_20220929_000011_u_ocps_85f23b5af0ba44cf967f183c59b1073e_run.yaml'}, {'id': 27, 'uri': '/uws/jobs/85f23b5af0ba44cf967f183c59b1073e/out/verifyBiasExpStats_LATISS_white_empty~holo4_003_AT_O_20220929_000018_u_ocps_85f23b5af0ba44cf967f183c59b1073e_run.yaml'}, {'id': 28, 'uri': '/uws/jobs/85f23b5af0ba44cf967f183c59b1073e/out/verifyBiasExpStats_LATISS_white_empty~holo4_003_AT_O_20220929_000010_u_ocps_85f23b5af0ba44cf967f183c59b1073e_run.yaml'},{'id': 29, 'uri': '/uws/jobs/85f23b5af0ba44cf967f183c59b1073e/out/verifyBiasExpStats_LATISS_white_empty~holo4_003_AT_O_20220929_000006_u_ocps_85f23b5af0ba44cf967f183c59b1073e_run.yaml'}, {'id': 30, 'uri': '/uws/jobs/85f23b5af0ba44cf967f183c59b1073e/out/verifyBiasExpStats_LATISS_white_empty~holo4_003_AT_O_20220929_000013_u_ocps_85f23b5af0ba44cf967f183c59b1073e_run.yaml'}, {'id': 31, 'uri': '/uws/jobs/85f23b5af0ba44cf967f183c59b1073e/out/verifyBiasExpStats_LATISS_white_empty~holo4_003_AT_O_20220929_000012_u_ocps_85f23b5af0ba44cf967f183c59b1073e_run.yaml'},{'id': 32, 'uri': '/uws/jobs/85f23b5af0ba44cf967f183c59b1073e/out/verifyBiasExpStats_LATISS_white_empty~holo4_003_AT_O_20220929_000007_u_ocps_85f23b5af0ba44cf967f183c59b1073e_run.yaml'}, {'id': 61, 'uri': '/uws/jobs/85f23b5af0ba44cf967f183c59b1073e/out/verifyBiasDetStats_LATISS_empty~holo4_003_AT_O_20220929_000019_RXX_S00_u_ocps_85f23b5af0ba44cf967f183c59b1073e_run.yaml'}, {'id': 62, 'uri': '/uws/jobs/85f23b5af0ba44cf967f183c59b1073e/out/verifyBiasStats_LATISS_u_ocps_85f23b5af0ba44cf967f183c59b1073e_run.yaml'}, {'id': 63, 'uri': '/uws/jobs/85f23b5af0ba44cf967f183c59b1073e/out/verifyBiasDetStats_LATISS_empty~holo4_003_AT_O_20220929_000020_RXX_S00_u_ocps_85f23b5af0ba44cf967f183c59b1073e_run.yaml'}, {'id': 64, 'uri': '/uws/jobs/85f23b5af0ba44cf967f183c59b1073e/out/verifyBiasDetStats_LATISS_empty~holo4_003_AT_O_20220929_000004_RXX_S00_u_ocps_85f23b5af0ba44cf967f183c59b1073e_run.yaml'}, {'id': 65, 'uri': '/uws/jobs/85f23b5af0ba44cf967f183c59b1073e/out/verifyBiasDetStats_LATISS_empty~holo4_003_AT_O_20220929_000017_RXX_S00_u_ocps_85f23b5af0ba44cf967f183c59b1073e_run.yaml'}] }

        return response_verify

    async def mock_verify_stats_bias(self):
        verify_stats_bias = {2022110300071: {'FAILURES': ['RXX_S00 C00 NOISE', 'RXX_S00 C00 PROCESSING',
            'RXX_S00 C01 CR_NOISE', 'RXX_S00 C01 NOISE', 'RXX_S00 C01 PROCESSING', 'RXX_S00 C02 CR_NOISE',
            'RXX_S00 C02 NOISE', 'RXX_S00 C02 PROCESSING', 'RXX_S00 C03 CR_NOISE', 'RXX_S00 C03 NOISE',
            'RXX_S00 C03 PROCESSING', 'RXX_S00 C04 CR_NOISE', 'RXX_S00 C04 NOISE', 'RXX_S00 C04 PROCESSING',
            'RXX_S00 C05 CR_NOISE', 'RXX_S00 C05 NOISE', 'RXX_S00 C05 PROCESSING', 'RXX_S00 C06 NOISE',
            'RXX_S00 C06 PROCESSING', 'RXX_S00 C07 CR_NOISE', 'RXX_S00 C07 NOISE', 'RXX_S00 C07 PROCESSING',
            'RXX_S00 C10 CR_NOISE', 'RXX_S00 C10 NOISE', 'RXX_S00 C10 PROCESSING', 'RXX_S00 C11 CR_NOISE',
            'RXX_S00 C11 NOISE', 'RXX_S00 C11 PROCESSING', 'RXX_S00 C12 CR_NOISE', 'RXX_S00 C12 NOISE',
            'RXX_S00 C12 PROCESSING', 'RXX_S00 C13 CR_NOISE', 'RXX_S00 C13 NOISE', 'RXX_S00 C13 PROCESSING',
            'RXX_S00 C14 CR_NOISE', 'RXX_S00 C14 NOISE', 'RXX_S00 C14 PROCESSING', 'RXX_S00 C15 CR_NOISE',
            'RXX_S00 C15 NOISE', 'RXX_S00 C15 PROCESSING', 'RXX_S00 C16 CR_NOISE', 'RXX_S00 C16 NOISE',
            'RXX_S00 C16 PROCESSING', 'RXX_S00 C17 CR_NOISE', 'RXX_S00 C17 NOISE', 'RXX_S00 C17 PROCESSING']},
            2022110300072: {'FAILURES': ['RXX_S00 C00 NOISE', 'RXX_S00 C00 PROCESSING', 'RXX_S00 C01
            CR_NOISE', 'RXX_S00 C01 NOISE', 'RXX_S00 C01 PROCESSING', 'RXX_S00 C02 CR_NOISE', 'RXX_S00 C02
            NOISE', 'RXX_S00 C02 PROCESSING', 'RXX_S00 C03 CR_NOISE', 'RXX_S00 C03 NOISE', 'RXX_S00 C03
            PROCESSING', 'RXX_S00 C04 CR_NOISE', 'RXX_S00 C04 NOISE', 'RXX_S00 C04 PROCESSING', 'RXX_S00 C05
            CR_NOISE', 'RXX_S00 C05 NOISE', 'RXX_S00 C05 PROCESSING', 'RXX_S00 C06 NOISE', 'RXX_S00 C06
            PROCESSING', 'RXX_S00 C07 CR_NOISE', 'RXX_S00 C07 NOISE', 'RXX_S00 C07 PROCESSING', 'RXX_S00 C10
            CR_NOISE', 'RXX_S00 C10 NOISE', 'RXX_S00 C10 PROCESSING', 'RXX_S00 C11 CR_NOISE', 'RXX_S00 C11
            NOISE', 'RXX_S00 C11 PROCESSING', 'RXX_S00 C12 CR_NOISE', 'RXX_S00 C12 NOISE', 'RXX_S00 C12
            PROCESSING', 'RXX_S00 C13 CR_NOISE', 'RXX_S00 C13 NOISE', 'RXX_S00 C13 PROCESSING', 'RXX_S00 C14
            CR_NOISE', 'RXX_S00 C14 NOISE', 'RXX_S00 C14 PROCESSING', 'RXX_S00 C15 CR_NOISE', 'RXX_S00 C15
            NOISE', 'RXX_S00 C15 PROCESSING', 'RXX_S00 C16 CR_NOISE', 'RXX_S00 C16 NOISE', 'RXX_S00 C16
            PROCESSING', 'RXX_S00 C17 CR_NOISE', 'RXX_S00 C17 NOISE', 'RXX_S00 C17 PROCESSING']},
            2022110300073: {'FAILURES': ['RXX_S00 C00 NOISE', 'RXX_S00 C00 PROCESSING', 'RXX_S00 C01
            CR_NOISE', 'RXX_S00 C01 NOISE', 'RXX_S00 C01 PROCESSING', 'RXX_S00 C02 CR_NOISE', 'RXX_S00 C02
            NOISE', 'RXX_S00 C02 PROCESSING', 'RXX_S00 C03 CR_NOISE', 'RXX_S00 C03 NOISE', 'RXX_S00 C03
            PROCESSING', 'RXX_S00 C04 CR_NOISE', 'RXX_S00 C04 NOISE', 'RXX_S00 C04 PROCESSING', 'RXX_S00 C05
            CR_NOISE', 'RXX_S00 C05 NOISE', 'RXX_S00 C05 PROCESSING', 'RXX_S00 C06 NOISE', 'RXX_S00 C06
            PROCESSING', 'RXX_S00 C07 CR_NOISE', 'RXX_S00 C07 NOISE', 'RXX_S00 C07 PROCESSING', 'RXX_S00 C10
            CR_NOISE', 'RXX_S00 C10 NOISE', 'RXX_S00 C10 PROCESSING', 'RXX_S00 C11 CR_NOISE', 'RXX_S00 C11
            NOISE', 'RXX_S00 C11 PROCESSING', 'RXX_S00 C12 CR_NOISE', 'RXX_S00 C12 NOISE', 'RXX_S00 C12
            PROCESSING', 'RXX_S00 C13 CR_NOISE', 'RXX_S00 C13 NOISE', 'RXX_S00 C13 PROCESSING', 'RXX_S00 C14
            CR_NOISE', 'RXX_S00 C14 NOISE', 'RXX_S00 C14 PROCESSING', 'RXX_S00 C15 CR_NOISE', 'RXX_S00 C15
            NOISE', 'RXX_S00 C15 PROCESSING', 'RXX_S00 C16 CR_NOISE', 'RXX_S00 C16 NOISE', 'RXX_S00 C16
            PROCESSING', 'RXX_S00 C17 CR_NOISE', 'RXX_S00 C17 NOISE', 'RXX_S00 C17 PROCESSING']},
            2022110300074: {'FAILURES': ['RXX_S00 C00 NOISE', 'RXX_S00 C00 PROCESSING', 'RXX_S00 C01
            CR_NOISE', 'RXX_S00 C01 NOISE', 'RXX_S00 C01 PROCESSING', 'RXX_S00 C02 CR_NOISE', 'RXX_S00 C02
            NOISE', 'RXX_S00 C02 PROCESSING', 'RXX_S00 C03 CR_NOISE', 'RXX_S00 C03 NOISE', 'RXX_S00 C03
            PROCESSING', 'RXX_S00 C04 CR_NOISE', 'RXX_S00 C04 NOISE', 'RXX_S00 C04 PROCESSING', 'RXX_S00 C05
            CR_NOISE', 'RXX_S00 C05 NOISE', 'RXX_S00 C05 PROCESSING', 'RXX_S00 C06 NOISE', 'RXX_S00 C06
            PROCESSING', 'RXX_S00 C07 CR_NOISE', 'RXX_S00 C07 NOISE', 'RXX_S00 C07 PROCESSING', 'RXX_S00 C10
            CR_NOISE', 'RXX_S00 C10 NOISE', 'RXX_S00 C10 PROCESSING', 'RXX_S00 C11 CR_NOISE', 'RXX_S00 C11
            NOISE', 'RXX_S00 C11 PROCESSING', 'RXX_S00 C12 CR_NOISE', 'RXX_S00 C12 NOISE', 'RXX_S00 C12
            PROCESSING', 'RXX_S00 C13 CR_NOISE', 'RXX_S00 C13 NOISE', 'RXX_S00 C13 PROCESSING', 'RXX_S00 C14
            CR_NOISE', 'RXX_S00 C14 NOISE', 'RXX_S00 C14 PROCESSING', 'RXX_S00 C15 CR_NOISE', 'RXX_S00 C15
            NOISE', 'RXX_S00 C15 PROCESSING', 'RXX_S00 C16 CR_NOISE', 'RXX_S00 C16 NOISE', 'RXX_S00 C16
            PROCESSING', 'RXX_S00 C17 CR_NOISE', 'RXX_S00 C17 NOISE', 'RXX_S00 C17 PROCESSING']},
            2022110300075: {'FAILURES': ['RXX_S00 C00 NOISE', 'RXX_S00 C00 PROCESSING', 'RXX_S00 C01
            CR_NOISE', 'RXX_S00 C01 NOISE', 'RXX_S00 C01 PROCESSING', 'RXX_S00 C02 CR_NOISE', 'RXX_S00 C02
            NOISE', 'RXX_S00 C02 PROCESSING', 'RXX_S00 C03 CR_NOISE', 'RXX_S00 C03 NOISE', 'RXX_S00 C03
            PROCESSING', 'RXX_S00 C04 CR_NOISE', 'RXX_S00 C04 NOISE', 'RXX_S00 C04 PROCESSING', 'RXX_S00 C05
            CR_NOISE', 'RXX_S00 C05 NOISE', 'RXX_S00 C05 PROCESSING', 'RXX_S00 C06 NOISE', 'RXX_S00 C06
            PROCESSING', 'RXX_S00 C07 CR_NOISE', 'RXX_S00 C07 NOISE', 'RXX_S00 C07 PROCESSING', 'RXX_S00 C10
            CR_NOISE', 'RXX_S00 C10 NOISE', 'RXX_S00 C10 PROCESSING', 'RXX_S00 C11 CR_NOISE', 'RXX_S00 C11
            NOISE', 'RXX_S00 C11 PROCESSING', 'RXX_S00 C12 CR_NOISE', 'RXX_S00 C12 NOISE', 'RXX_S00 C12
            PROCESSING', 'RXX_S00 C13 CR_NOISE', 'RXX_S00 C13 NOISE', 'RXX_S00 C13 PROCESSING', 'RXX_S00 C14
            CR_NOISE', 'RXX_S00 C14 NOISE', 'RXX_S00 C14 PROCESSING', 'RXX_S00 C15 CR_NOISE', 'RXX_S00 C15
            NOISE', 'RXX_S00 C15 PROCESSING', 'RXX_S00 C16 CR_NOISE', 'RXX_S00 C16 NOISE', 'RXX_S00 C16
            PROCESSING', 'RXX_S00 C17 CR_NOISE', 'RXX_S00 C17 NOISE', 'RXX_S00 C17 PROCESSING']},
            2022110300076: {'FAILURES': ['RXX_S00 C00 NOISE', 'RXX_S00 C00 PROCESSING', 'RXX_S00 C01
            CR_NOISE', 'RXX_S00 C01 NOISE', 'RXX_S00 C01 PROCESSING', 'RXX_S00 C02 CR_NOISE', 'RXX_S00 C02
            NOISE', 'RXX_S00 C02 PROCESSING', 'RXX_S00 C03 CR_NOISE', 'RXX_S00 C03 NOISE', 'RXX_S00 C03
            PROCESSING', 'RXX_S00 C04 CR_NOISE', 'RXX_S00 C04 NOISE', 'RXX_S00 C04 PROCESSING', 'RXX_S00 C05
            CR_NOISE', 'RXX_S00 C05 NOISE', 'RXX_S00 C05 PROCESSING', 'RXX_S00 C06 NOISE', 'RXX_S00 C06
            PROCESSING', 'RXX_S00 C07 CR_NOISE', 'RXX_S00 C07 NOISE', 'RXX_S00 C07 PROCESSING', 'RXX_S00 C10
            CR_NOISE', 'RXX_S00 C10 NOISE', 'RXX_S00 C10 PROCESSING', 'RXX_S00 C11 CR_NOISE', 'RXX_S00 C11
            NOISE', 'RXX_S00 C11 PROCESSING', 'RXX_S00 C12 CR_NOISE', 'RXX_S00 C12 NOISE', 'RXX_S00 C12
            PROCESSING', 'RXX_S00 C13 CR_NOISE', 'RXX_S00 C13 NOISE', 'RXX_S00 C13 PROCESSING', 'RXX_S00 C14
            CR_NOISE', 'RXX_S00 C14 NOISE', 'RXX_S00 C14 PROCESSING', 'RXX_S00 C15 CR_NOISE', 'RXX_S00 C15
            NOISE', 'RXX_S00 C15 PROCESSING', 'RXX_S00 C16 CR_NOISE', 'RXX_S00 C16 NOISE', 'RXX_S00 C16
            PROCESSING', 'RXX_S00 C17 CR_NOISE', 'RXX_S00 C17 NOISE', 'RXX_S00 C17 PROCESSING']},
            2022110300077: {'FAILURES': ['RXX_S00 C00 NOISE', 'RXX_S00 C00 PROCESSING', 'RXX_S00 C01
            CR_NOISE', 'RXX_S00 C01 NOISE', 'RXX_S00 C01 PROCESSING', 'RXX_S00 C02 CR_NOISE', 'RXX_S00 C02
            NOISE', 'RXX_S00 C02 PROCESSING', 'RXX_S00 C03 CR_NOISE', 'RXX_S00 C03 NOISE', 'RXX_S00 C03
            PROCESSING', 'RXX_S00 C04 CR_NOISE', 'RXX_S00 C04 NOISE', 'RXX_S00 C04 PROCESSING', 'RXX_S00 C05
            CR_NOISE', 'RXX_S00 C05 NOISE', 'RXX_S00 C05 PROCESSING', 'RXX_S00 C06 NOISE', 'RXX_S00 C06
            PROCESSING', 'RXX_S00 C07 CR_NOISE', 'RXX_S00 C07 NOISE', 'RXX_S00 C07 PROCESSING', 'RXX_S00 C10
            CR_NOISE', 'RXX_S00 C10 NOISE', 'RXX_S00 C10 PROCESSING', 'RXX_S00 C11 CR_NOISE', 'RXX_S00 C11
            NOISE', 'RXX_S00 C11 PROCESSING', 'RXX_S00 C12 CR_NOISE', 'RXX_S00 C12 NOISE', 'RXX_S00 C12
            PROCESSING', 'RXX_S00 C13 CR_NOISE', 'RXX_S00 C13 NOISE', 'RXX_S00 C13 PROCESSING', 'RXX_S00 C14
            CR_NOISE', 'RXX_S00 C14 NOISE', 'RXX_S00 C14 PROCESSING', 'RXX_S00 C15 CR_NOISE', 'RXX_S00 C15
            NOISE', 'RXX_S00 C15 PROCESSING', 'RXX_S00 C16 CR_NOISE', 'RXX_S00 C16 NOISE', 'RXX_S00 C16
            PROCESSING', 'RXX_S00 C17 CR_NOISE', 'RXX_S00 C17 NOISE', 'RXX_S00 C17 PROCESSING']},
            2022110300078: {'FAILURES': ['RXX_S00 C00 NOISE', 'RXX_S00 C00 PROCESSING', 'RXX_S00 C01
            CR_NOISE', 'RXX_S00 C01 NOISE', 'RXX_S00 C01 PROCESSING', 'RXX_S00 C02 CR_NOISE', 'RXX_S00 C02
            NOISE', 'RXX_S00 C02 PROCESSING', 'RXX_S00 C03 CR_NOISE', 'RXX_S00 C03 NOISE', 'RXX_S00 C03
            PROCESSING', 'RXX_S00 C04 CR_NOISE', 'RXX_S00 C04 NOISE', 'RXX_S00 C04 PROCESSING', 'RXX_S00 C05
            CR_NOISE', 'RXX_S00 C05 NOISE', 'RXX_S00 C05 PROCESSING', 'RXX_S00 C06 NOISE', 'RXX_S00 C06
            PROCESSING', 'RXX_S00 C07 CR_NOISE', 'RXX_S00 C07 NOISE', 'RXX_S00 C07 PROCESSING', 'RXX_S00 C10
            CR_NOISE', 'RXX_S00 C10 NOISE', 'RXX_S00 C10 PROCESSING', 'RXX_S00 C11 CR_NOISE', 'RXX_S00 C11
            NOISE', 'RXX_S00 C11 PROCESSING', 'RXX_S00 C12 CR_NOISE', 'RXX_S00 C12 NOISE', 'RXX_S00 C12
            PROCESSING', 'RXX_S00 C13 CR_NOISE', 'RXX_S00 C13 NOISE', 'RXX_S00 C13 PROCESSING', 'RXX_S00 C14
            CR_NOISE', 'RXX_S00 C14 NOISE', 'RXX_S00 C14 PROCESSING', 'RXX_S00 C15 CR_NOISE', 'RXX_S00 C15
            NOISE', 'RXX_S00 C15 PROCESSING', 'RXX_S00 C16 CR_NOISE', 'RXX_S00 C16 NOISE', 'RXX_S00 C16
            PROCESSING', 'RXX_S00 C17 CR_NOISE', 'RXX_S00 C17 NOISE', 'RXX_S00 C17 PROCESSING']},
            2022110300079: {'FAILURES': ['RXX_S00 C00 NOISE', 'RXX_S00 C00 PROCESSING', 'RXX_S00 C01
            CR_NOISE', 'RXX_S00 C01 NOISE', 'RXX_S00 C01 PROCESSING', 'RXX_S00 C02 CR_NOISE', 'RXX_S00 C02
            NOISE', 'RXX_S00 C02 PROCESSING', 'RXX_S00 C03 CR_NOISE', 'RXX_S00 C03 NOISE', 'RXX_S00 C03
            PROCESSING', 'RXX_S00 C04 CR_NOISE', 'RXX_S00 C04 NOISE', 'RXX_S00 C04 PROCESSING', 'RXX_S00 C05
            CR_NOISE', 'RXX_S00 C05 NOISE', 'RXX_S00 C05 PROCESSING', 'RXX_S00 C06 NOISE', 'RXX_S00 C06
            PROCESSING', 'RXX_S00 C07 CR_NOISE', 'RXX_S00 C07 NOISE', 'RXX_S00 C07 PROCESSING', 'RXX_S00 C10
            CR_NOISE', 'RXX_S00 C10 NOISE', 'RXX_S00 C10 PROCESSING', 'RXX_S00 C11 CR_NOISE', 'RXX_S00 C11
            NOISE', 'RXX_S00 C11 PROCESSING', 'RXX_S00 C12 CR_NOISE', 'RXX_S00 C12 NOISE', 'RXX_S00 C12
            PROCESSING', 'RXX_S00 C13 CR_NOISE', 'RXX_S00 C13 NOISE', 'RXX_S00 C13 PROCESSING', 'RXX_S00 C14
            CR_NOISE', 'RXX_S00 C14 NOISE', 'RXX_S00 C14 PROCESSING', 'RXX_S00 C15 CR_NOISE', 'RXX_S00 C15
            NOISE', 'RXX_S00 C15 PROCESSING', 'RXX_S00 C16 CR_NOISE', 'RXX_S00 C16 NOISE', 'RXX_S00 C16
            PROCESSING', 'RXX_S00 C17 CR_NOISE', 'RXX_S00 C17 NOISE', 'RXX_S00 C17 PROCESSING']},
            2022110300080: {'FAILURES': ['RXX_S00 C00 NOISE', 'RXX_S00 C00 PROCESSING', 'RXX_S00 C01
            CR_NOISE', 'RXX_S00 C01 NOISE', 'RXX_S00 C01 PROCESSING', 'RXX_S00 C02 CR_NOISE', 'RXX_S00 C02
            NOISE', 'RXX_S00 C02 PROCESSING', 'RXX_S00 C03 CR_NOISE', 'RXX_S00 C03 NOISE', 'RXX_S00 C03
            PROCESSING', 'RXX_S00 C04 CR_NOISE', 'RXX_S00 C04 NOISE', 'RXX_S00 C04 PROCESSING', 'RXX_S00 C05
            NOISE', 'RXX_S00 C05 PROCESSING', 'RXX_S00 C06 NOISE', 'RXX_S00 C06 PROCESSING', 'RXX_S00 C07
            CR_NOISE', 'RXX_S00 C07 NOISE', 'RXX_S00 C07 PROCESSING', 'RXX_S00 C10 CR_NOISE', 'RXX_S00 C10
            NOISE', 'RXX_S00 C10 PROCESSING', 'RXX_S00 C11 CR_NOISE', 'RXX_S00 C11 NOISE', 'RXX_S00 C11
            PROCESSING', 'RXX_S00 C12 CR_NOISE', 'RXX_S00 C12 NOISE', 'RXX_S00 C12 PROCESSING', 'RXX_S00 C13
            CR_NOISE', 'RXX_S00 C13 NOISE', 'RXX_S00 C13 PROCESSING', 'RXX_S00 C14 CR_NOISE', 'RXX_S00 C14
            NOISE', 'RXX_S00 C14 PROCESSING', 'RXX_S00 C15 CR_NOISE', 'RXX_S00 C15 NOISE', 'RXX_S00 C15
            PROCESSING', 'RXX_S00 C16 CR_NOISE', 'RXX_S00 C16 NOISE', 'RXX_S00 C16 PROCESSING', 'RXX_S00 C17
            CR_NOISE', 'RXX_S00 C17 NOISE', 'RXX_S00 C17 PROCESSING']}, 2022110300081: {'FAILURES': ['RXX_S00
            C00 NOISE', 'RXX_S00 C00 PROCESSING', 'RXX_S00 C01 CR_NOISE', 'RXX_S00 C01 NOISE', 'RXX_S00 C01
            PROCESSING', 'RXX_S00 C02 CR_NOISE', 'RXX_S00 C02 NOISE', 'RXX_S00 C02 PROCESSING', 'RXX_S00 C03
            CR_NOISE', 'RXX_S00 C03 NOISE', 'RXX_S00 C03 PROCESSING', 'RXX_S00 C04 CR_NOISE', 'RXX_S00 C04
            NOISE', 'RXX_S00 C04 PROCESSING', 'RXX_S00 C05 CR_NOISE', 'RXX_S00 C05 NOISE', 'RXX_S00 C05
            PROCESSING', 'RXX_S00 C06 NOISE', 'RXX_S00 C06 PROCESSING', 'RXX_S00 C07 CR_NOISE', 'RXX_S00 C07
            NOISE', 'RXX_S00 C07 PROCESSING', 'RXX_S00 C10 CR_NOISE', 'RXX_S00 C10 NOISE', 'RXX_S00 C10
            PROCESSING', 'RXX_S00 C11 CR_NOISE', 'RXX_S00 C11 NOISE', 'RXX_S00 C11 PROCESSING', 'RXX_S00 C12
            CR_NOISE', 'RXX_S00 C12 NOISE', 'RXX_S00 C12 PROCESSING', 'RXX_S00 C13 CR_NOISE', 'RXX_S00 C13
            NOISE', 'RXX_S00 C13 PROCESSING', 'RXX_S00 C14 CR_NOISE', 'RXX_S00 C14 NOISE', 'RXX_S00 C14
            PROCESSING', 'RXX_S00 C15 CR_NOISE', 'RXX_S00 C15 NOISE', 'RXX_S00 C15 PROCESSING', 'RXX_S00 C16
            CR_NOISE', 'RXX_S00 C16 NOISE', 'RXX_S00 C16 PROCESSING', 'RXX_S00 C17 CR_NOISE', 'RXX_S00 C17
            NOISE', 'RXX_S00 C17 PROCESSING']}, 2022110300082: {'FAILURES': ['RXX_S00 C00 NOISE', 'RXX_S00 C00
            PROCESSING', 'RXX_S00 C01 CR_NOISE', 'RXX_S00 C01 NOISE', 'RXX_S00 C01 PROCESSING', 'RXX_S00 C02
            CR_NOISE', 'RXX_S00 C02 NOISE', 'RXX_S00 C02 PROCESSING', 'RXX_S00 C03 CR_NOISE', 'RXX_S00 C03
            NOISE', 'RXX_S00 C03 PROCESSING', 'RXX_S00 C04 CR_NOISE', 'RXX_S00 C04 NOISE', 'RXX_S00 C04
            PROCESSING', 'RXX_S00 C05 CR_NOISE', 'RXX_S00 C05 NOISE', 'RXX_S00 C05 PROCESSING', 'RXX_S00 C06
            NOISE', 'RXX_S00 C06 PROCESSING', 'RXX_S00 C07 CR_NOISE', 'RXX_S00 C07 NOISE', 'RXX_S00 C07
            PROCESSING', 'RXX_S00 C10 CR_NOISE', 'RXX_S00 C10 NOISE', 'RXX_S00 C10 PROCESSING', 'RXX_S00 C11
            CR_NOISE', 'RXX_S00 C11 NOISE', 'RXX_S00 C11 PROCESSING', 'RXX_S00 C12 CR_NOISE', 'RXX_S00 C12
            NOISE', 'RXX_S00 C12 PROCESSING', 'RXX_S00 C13 CR_NOISE', 'RXX_S00 C13 NOISE', 'RXX_S00 C13
            PROCESSING', 'RXX_S00 C14 CR_NOISE', 'RXX_S00 C14 NOISE', 'RXX_S00 C14 PROCESSING', 'RXX_S00 C15
            CR_NOISE', 'RXX_S00 C15 NOISE', 'RXX_S00 C15 PROCESSING', 'RXX_S00 C16 CR_NOISE', 'RXX_S00 C16
            NOISE', 'RXX_S00 C16 PROCESSING', 'RXX_S00 C17 CR_NOISE', 'RXX_S00 C17 NOISE', 'RXX_S00 C17
            PROCESSING']}, 2022110300083: {'FAILURES': ['RXX_S00 C00 NOISE', 'RXX_S00 C00 PROCESSING',
                'RXX_S00 C01 CR_NOISE', 'RXX_S00 C01 NOISE', 'RXX_S00 C01 PROCESSING', 'RXX_S00 C02 CR_NOISE',
                'RXX_S00 C02 NOISE', 'RXX_S00 C02 PROCESSING', 'RXX_S00 C03 CR_NOISE', 'RXX_S00 C03 NOISE',
                'RXX_S00 C03 PROCESSING', 'RXX_S00 C04 CR_NOISE', 'RXX_S00 C04 NOISE', 'RXX_S00 C04
                PROCESSING', 'RXX_S00 C05 CR_NOISE', 'RXX_S00 C05 NOISE', 'RXX_S00 C05 PROCESSING', 'RXX_S00
                C06 NOISE', 'RXX_S00 C06 PROCESSING', 'RXX_S00 C07 CR_NOISE', 'RXX_S00 C07 NOISE', 'RXX_S00
                C07 PROCESSING', 'RXX_S00 C10 CR_NOISE', 'RXX_S00 C10 NOISE', 'RXX_S00 C10 PROCESSING',
                'RXX_S00 C11 CR_NOISE', 'RXX_S00 C11 NOISE', 'RXX_S00 C11 PROCESSING', 'RXX_S00 C12 CR_NOISE',
                'RXX_S00 C12 NOISE', 'RXX_S00 C12 PROCESSING', 'RXX_S00 C13 CR_NOISE', 'RXX_S00 C13 NOISE',
                'RXX_S00 C13 PROCESSING', 'RXX_S00 C14 CR_NOISE', 'RXX_S00 C14 NOISE', 'RXX_S00 C14
                PROCESSING', 'RXX_S00 C15 CR_NOISE', 'RXX_S00 C15 NOISE', 'RXX_S00 C15 PROCESSING', 'RXX_S00
                C16 CR_NOISE', 'RXX_S00 C16 NOISE', 'RXX_S00 C16 PROCESSING', 'RXX_S00 C17 CR_NOISE', 'RXX_S00
                C17 NOISE', 'RXX_S00 C17 PROCESSING']}, 2022110300084: {'FAILURES': ['RXX_S00 C00 NOISE',
                    'RXX_S00 C00 PROCESSING', 'RXX_S00 C01 CR_NOISE', 'RXX_S00 C01 NOISE', 'RXX_S00 C01
                    PROCESSING', 'RXX_S00 C02 CR_NOISE', 'RXX_S00 C02 NOISE', 'RXX_S00 C02 PROCESSING',
                    'RXX_S00 C03 CR_NOISE', 'RXX_S00 C03 NOISE', 'RXX_S00 C03 PROCESSING', 'RXX_S00 C04
                    CR_NOISE', 'RXX_S00 C04 NOISE', 'RXX_S00 C04 PROCESSING', 'RXX_S00 C05 CR_NOISE', 'RXX_S00
                    C05 NOISE', 'RXX_S00 C05 PROCESSING', 'RXX_S00 C06 NOISE', 'RXX_S00 C06 PROCESSING',
                    'RXX_S00 C07 CR_NOISE', 'RXX_S00 C07 NOISE', 'RXX_S00 C07 PROCESSING', 'RXX_S00 C10
                    CR_NOISE', 'RXX_S00 C10 NOISE', 'RXX_S00 C10 PROCESSING', 'RXX_S00 C11 CR_NOISE', 'RXX_S00
                    C11 NOISE', 'RXX_S00 C11 PROCESSING', 'RXX_S00 C12 CR_NOISE', 'RXX_S00 C12 NOISE',
                    'RXX_S00 C12 PROCESSING', 'RXX_S00 C13 CR_NOISE', 'RXX_S00 C13 NOISE', 'RXX_S00 C13
                    PROCESSING', 'RXX_S00 C14 CR_NOISE', 'RXX_S00 C14 NOISE', 'RXX_S00 C14 PROCESSING',
                    'RXX_S00 C15 CR_NOISE', 'RXX_S00 C15 NOISE', 'RXX_S00 C15 PROCESSING', 'RXX_S00 C16
                    CR_NOISE', 'RXX_S00 C16 NOISE', 'RXX_S00 C16 PROCESSING', 'RXX_S00 C17 CR_NOISE', 'RXX_S00
                    C17 NOISE', 'RXX_S00 C17 PROCESSING']}, 2022110300085: {'FAILURES': ['RXX_S00 C00 NOISE',
                        'RXX_S00 C00 PROCESSING', 'RXX_S00 C01 CR_NOISE', 'RXX_S00 C01 NOISE', 'RXX_S00 C01
                        PROCESSING', 'RXX_S00 C02 CR_NOISE', 'RXX_S00 C02 NOISE', 'RXX_S00 C02 PROCESSING',
                        'RXX_S00 C03 CR_NOISE', 'RXX_S00 C03 NOISE', 'RXX_S00 C03 PROCESSING', 'RXX_S00 C04
                        CR_NOISE', 'RXX_S00 C04 NOISE', 'RXX_S00 C04 PROCESSING', 'RXX_S00 C05 CR_NOISE',
                        'RXX_S00 C05 NOISE', 'RXX_S00 C05 PROCESSING', 'RXX_S00 C06 NOISE', 'RXX_S00 C06
                        PROCESSING', 'RXX_S00 C07 CR_NOISE', 'RXX_S00 C07 NOISE', 'RXX_S00 C07 PROCESSING',
                        'RXX_S00 C10 CR_NOISE', 'RXX_S00 C10 NOISE', 'RXX_S00 C10 PROCESSING', 'RXX_S00 C11
                        CR_NOISE', 'RXX_S00 C11 NOISE', 'RXX_S00 C11 PROCESSING', 'RXX_S00 C12 CR_NOISE',
                        'RXX_S00 C12 NOISE', 'RXX_S00 C12 PROCESSING', 'RXX_S00 C13 CR_NOISE', 'RXX_S00 C13
                        NOISE', 'RXX_S00 C13 PROCESSING', 'RXX_S00 C14 CR_NOISE', 'RXX_S00 C14 NOISE',
                        'RXX_S00 C14 PROCESSING', 'RXX_S00 C15 CR_NOISE', 'RXX_S00 C15 NOISE', 'RXX_S00 C15
                        PROCESSING', 'RXX_S00 C16 CR_NOISE', 'RXX_S00 C16 NOISE', 'RXX_S00 C16 PROCESSING',
                        'RXX_S00 C17 CR_NOISE', 'RXX_S00 C17 NOISE', 'RXX_S00 C17 PROCESSING']},
                    2022110300086: {'FAILURES': ['RXX_S00 C00 NOISE', 'RXX_S00 C00 PROCESSING', 'RXX_S00 C01
                    CR_NOISE', 'RXX_S00 C01 NOISE', 'RXX_S00 C01 PROCESSING', 'RXX_S00 C02 CR_NOISE', 'RXX_S00
                    C02 NOISE', 'RXX_S00 C02 PROCESSING', 'RXX_S00 C03 CR_NOISE', 'RXX_S00 C03 NOISE',
                    'RXX_S00 C03 PROCESSING', 'RXX_S00 C04 CR_NOISE', 'RXX_S00 C04 NOISE', 'RXX_S00 C04
                    PROCESSING', 'RXX_S00 C05 NOISE', 'RXX_S00 C05 PROCESSING', 'RXX_S00 C06 NOISE', 'RXX_S00
                    C06 PROCESSING', 'RXX_S00 C07 CR_NOISE', 'RXX_S00 C07 NOISE', 'RXX_S00 C07 PROCESSING',
                    'RXX_S00 C10 CR_NOISE', 'RXX_S00 C10 NOISE', 'RXX_S00 C10 PROCESSING', 'RXX_S00 C11
                    CR_NOISE', 'RXX_S00 C11 NOISE', 'RXX_S00 C11 PROCESSING', 'RXX_S00 C12 CR_NOISE', 'RXX_S00
                    C12 NOISE', 'RXX_S00 C12 PROCESSING', 'RXX_S00 C13 CR_NOISE', 'RXX_S00 C13 NOISE',
                    'RXX_S00 C13 PROCESSING', 'RXX_S00 C14 CR_NOISE', 'RXX_S00 C14 NOISE', 'RXX_S00 C14
                    PROCESSING', 'RXX_S00 C15 CR_NOISE', 'RXX_S00 C15 NOISE', 'RXX_S00 C15 PROCESSING',
                    'RXX_S00 C16 CR_NOISE', 'RXX_S00 C16 NOISE', 'RXX_S00 C16 PROCESSING', 'RXX_S00 C17
                    CR_NOISE', 'RXX_S00 C17 NOISE', 'RXX_S00 C17 PROCESSING']}, 2022110300087: {'FAILURES':
                            ['RXX_S00 C00 NOISE', 'RXX_S00 C00 PROCESSING', 'RXX_S00 C01 CR_NOISE', 'RXX_S00
                            C01 NOISE', 'RXX_S00 C01 PROCESSING', 'RXX_S00 C02 CR_NOISE', 'RXX_S00 C02 NOISE',
                            'RXX_S00 C02 PROCESSING', 'RXX_S00 C03 CR_NOISE', 'RXX_S00 C03 NOISE', 'RXX_S00
                            C03 PROCESSING', 'RXX_S00 C04 CR_NOISE', 'RXX_S00 C04 NOISE', 'RXX_S00 C04
                            PROCESSING', 'RXX_S00 C05 CR_NOISE', 'RXX_S00 C05 NOISE', 'RXX_S00 C05
                            PROCESSING', 'RXX_S00 C06 NOISE', 'RXX_S00 C06 PROCESSING', 'RXX_S00 C07
                            CR_NOISE', 'RXX_S00 C07 NOISE', 'RXX_S00 C07 PROCESSING', 'RXX_S00 C10 CR_NOISE',
                            'RXX_S00 C10 NOISE', 'RXX_S00 C10 PROCESSING', 'RXX_S00 C11 CR_NOISE', 'RXX_S00
                            C11 NOISE', 'RXX_S00 C11 PROCESSING', 'RXX_S00 C12 CR_NOISE', 'RXX_S00 C12 NOISE',
                            'RXX_S00 C12 PROCESSING', 'RXX_S00 C13 CR_NOISE', 'RXX_S00 C13 NOISE', 'RXX_S00
                            C13 PROCESSING', 'RXX_S00 C14 CR_NOISE', 'RXX_S00 C14 NOISE', 'RXX_S00 C14
                            PROCESSING', 'RXX_S00 C15 CR_NOISE', 'RXX_S00 C15 NOISE', 'RXX_S00 C15
                            PROCESSING', 'RXX_S00 C16 CR_NOISE', 'RXX_S00 C16 NOISE', 'RXX_S00 C16
                            PROCESSING', 'RXX_S00 C17 CR_NOISE', 'RXX_S00 C17 NOISE', 'RXX_S00 C17
                            PROCESSING']}, 2022110300088: {'FAILURES': ['RXX_S00 C00 NOISE', 'RXX_S00 C00
                            PROCESSING', 'RXX_S00 C01 CR_NOISE', 'RXX_S00 C01 NOISE', 'RXX_S00 C01
                            PROCESSING', 'RXX_S00 C02 CR_NOISE', 'RXX_S00 C02 NOISE', 'RXX_S00 C02
                            PROCESSING', 'RXX_S00 C03 CR_NOISE', 'RXX_S00 C03 NOISE', 'RXX_S00 C03
                            PROCESSING', 'RXX_S00 C04 CR_NOISE', 'RXX_S00 C04 NOISE', 'RXX_S00 C04
                            PROCESSING', 'RXX_S00 C05 CR_NOISE', 'RXX_S00 C05 NOISE', 'RXX_S00 C05
                            PROCESSING', 'RXX_S00 C06 NOISE', 'RXX_S00 C06 PROCESSING', 'RXX_S00 C07
                            CR_NOISE', 'RXX_S00 C07 NOISE', 'RXX_S00 C07 PROCESSING', 'RXX_S00 C10 CR_NOISE',
                            'RXX_S00 C10 NOISE', 'RXX_S00 C10 PROCESSING', 'RXX_S00 C11 CR_NOISE', 'RXX_S00
                            C11 NOISE', 'RXX_S00 C11 PROCESSING', 'RXX_S00 C12 CR_NOISE', 'RXX_S00 C12 NOISE',
                            'RXX_S00 C12 PROCESSING', 'RXX_S00 C13 CR_NOISE', 'RXX_S00 C13 NOISE', 'RXX_S00
                            C13 PROCESSING', 'RXX_S00 C14 CR_NOISE', 'RXX_S00 C14 NOISE', 'RXX_S00 C14
                            PROCESSING', 'RXX_S00 C15 CR_NOISE', 'RXX_S00 C15 NOISE', 'RXX_S00 C15
                            PROCESSING', 'RXX_S00 C16 CR_NOISE', 'RXX_S00 C16 NOISE', 'RXX_S00 C16
                            PROCESSING', 'RXX_S00 C17 CR_NOISE', 'RXX_S00 C17 NOISE', 'RXX_S00 C17
                            PROCESSING']}, 2022110300089: {'FAILURES': ['RXX_S00 C00 NOISE', 'RXX_S00 C00
                            PROCESSING', 'RXX_S00 C01 CR_NOISE', 'RXX_S00 C01 NOISE', 'RXX_S00 C01
                            PROCESSING', 'RXX_S00 C02 CR_NOISE', 'RXX_S00 C02 NOISE', 'RXX_S00 C02
                            PROCESSING', 'RXX_S00 C03 CR_NOISE', 'RXX_S00 C03 NOISE', 'RXX_S00 C03
                            PROCESSING', 'RXX_S00 C04 CR_NOISE', 'RXX_S00 C04 NOISE', 'RXX_S00 C04
                            PROCESSING', 'RXX_S00 C05 CR_NOISE', 'RXX_S00 C05 NOISE', 'RXX_S00 C05
                            PROCESSING', 'RXX_S00 C06 NOISE', 'RXX_S00 C06 PROCESSING', 'RXX_S00 C07
                            CR_NOISE', 'RXX_S00 C07 NOISE', 'RXX_S00 C07 PROCESSING', 'RXX_S00 C10 CR_NOISE',
                            'RXX_S00 C10 NOISE', 'RXX_S00 C10 PROCESSING', 'RXX_S00 C11 CR_NOISE', 'RXX_S00
                            C11 NOISE', 'RXX_S00 C11 PROCESSING', 'RXX_S00 C12 CR_NOISE', 'RXX_S00 C12 NOISE',
                            'RXX_S00 C12 PROCESSING', 'RXX_S00 C13 CR_NOISE', 'RXX_S00 C13 NOISE', 'RXX_S00
                            C13 PROCESSING', 'RXX_S00 C14 CR_NOISE', 'RXX_S00 C14 NOISE', 'RXX_S00 C14
                            PROCESSING', 'RXX_S00 C15 CR_NOISE', 'RXX_S00 C15 NOISE', 'RXX_S00 C15
                            PROCESSING', 'RXX_S00 C16 CR_NOISE', 'RXX_S00 C16 NOISE', 'RXX_S00 C16
                            PROCESSING', 'RXX_S00 C17 CR_NOISE', 'RXX_S00 C17 NOISE', 'RXX_S00 C17
                            PROCESSING']}, 2022110300090: {'FAILURES': ['RXX_S00 C00 NOISE', 'RXX_S00 C00
                            PROCESSING', 'RXX_S00 C01 CR_NOISE', 'RXX_S00 C01 NOISE', 'RXX_S00 C01
                            PROCESSING', 'RXX_S00 C02 CR_NOISE', 'RXX_S00 C02 NOISE', 'RXX_S00 C02
                            PROCESSING', 'RXX_S00 C03 CR_NOISE', 'RXX_S00 C03 NOISE', 'RXX_S00 C03
                            PROCESSING', 'RXX_S00 C04 CR_NOISE', 'RXX_S00 C04 NOISE', 'RXX_S00 C04
                            PROCESSING', 'RXX_S00 C05 NOISE', 'RXX_S00 C05 PROCESSING', 'RXX_S00 C06
                            CR_NOISE', 'RXX_S00 C06 NOISE', 'RXX_S00 C06 PROCESSING', 'RXX_S00 C07 CR_NOISE',
                            'RXX_S00 C07 NOISE', 'RXX_S00 C07 PROCESSING', 'RXX_S00 C10 CR_NOISE', 'RXX_S00
                            C10 NOISE', 'RXX_S00 C10 PROCESSING', 'RXX_S00 C11 CR_NOISE', 'RXX_S00 C11 NOISE',
                            'RXX_S00 C11 PROCESSING', 'RXX_S00 C12 CR_NOISE', 'RXX_S00 C12 NOISE', 'RXX_S00
                            C12 PROCESSING', 'RXX_S00 C13 CR_NOISE', 'RXX_S00 C13 NOISE', 'RXX_S00 C13
                            PROCESSING', 'RXX_S00 C14 CR_NOISE', 'RXX_S00 C14 NOISE', 'RXX_S00 C14
                            PROCESSING', 'RXX_S00 C15 CR_NOISE', 'RXX_S00 C15 NOISE', 'RXX_S00 C15
                            PROCESSING', 'RXX_S00 C16 CR_NOISE', 'RXX_S00 C16 NOISE', 'RXX_S00 C16
                            PROCESSING', 'RXX_S00 C17 CR_NOISE', 'RXX_S00 C17 NOISE', 'RXX_S00 C17
                            PROCESSING']}, 'SUCCESS': False}
        return verify_stats_bias

