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

__all__ = ["CpVerifyAlarm"]

import yaml
import json
import lsst.daf.butler as dafButler
import salobj
import asyncio
import collections
import functools
from dataclasses import dataclass

from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts import watcher


class CpVerifyAlarm(watcher.BaseRule):
    """Monitor state of cp_verify executions from the OCPS
    for a particular type of calibration (BIAS, DARK, FLAT, etc).

    Set alarm severity NONE if the cp_verify tests passed,
    and issue a WARNNING  alarm if not.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.

    Notes
    -----
    The alarm name is f"CpVerifyAlarm.{ocps_index}:{calibration_type}",
    where ``calibration_type`` and ``ocps_index`` are derived from
    ``config.calibration_type`` and ``config.ocps_index``, respectively.
    """

    def __init__(self, config):
        remote_name = "OCPS"
        remote_index = config.ocps_index
        remote_info = watcher.RemoteInfo(
            name=remote_name,
            index=remote_index,
            callback_names=["job_result"],
            poll_names=[],
        )
        super().__init__(
            config=config,
            name=f"CpVerifyAlarm.{remote_info.index}:{remote_info.name}",
            remote_info_list=[remote_info],
        )

        self.calibration_type = config.calibration_type

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            description: Configuration for CpVerifyBiasAlarm
            type: object
            properties:
                calibration_type:
                    description: >-
                        Alarm calibration type: BIAS, DARK, or FLAT.
                    type: string
                    enum: ['BIAS', 'DARK', 'FLAT']
                ocps_index:
                    type: integer
                    enum: [1, 2]
                    description: >-
                        OCPS index (e.g., OCPS:1: LATISS; OCPS:2: LSSTComCam).
                verification_threshold:
                    type: integer
                    description: Maximum number of failures per detector per test type.
                    default: 8
            required:
              - calibration_type
              - ocps_index
              - verification_threshold
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    def __call__(self, data, topic_callback):
        # OCPS response after calling the pipetask
        ocps_result = json.loads(data.result)
        # Get the dictionary with cp_verify stats, from the butler.
        # It might be slow, so use `run_in_executor`
        loop = asyncio.get_running_loop()
        verify_stats = await loop.run_in_executor(
            None, self.get_cp_verify_stats, ocps_result
        )
        # boolean: did verification fail?
        return self.check_response(ocps_result, verify_stats)

    def check_response(self, ocps_result, verify_stats):
        """Determine if cp_verify tests passed from OCPS response.

        Parameters
        ----------
        ocps_result : `dict`
            OCPS call response.
        verify_stats: `dict`
            Dictionary with statistics after running ``cp_verify``.

        Returns
        -------
        AlarmSeverity : `lsst.ts.idl.enums.Watcher`
            Alarm severity.
        reason : `str`
            Reason for the alarm severity.

        Notes
        -----
            Examples of the OCPS call result and the ``cp_verify``
            statistics can be found in cp_verify_bias_stats.yaml,
            ocps_bias_verify_response.yaml, in
            ts_watcher/tests/rules/data/cp_verify_alarm.
        """
        verify_pass = True
        job_id_verify = ocps_result["job_id"]

        if verify_stats["SUCCESS"] is False:
            verification_tests = self.count_failed_verification_tests(
                verify_stats, self.config.verification_threshold
            )
            verify_pass = verification_tests.certify_calib
            thresholds = verification_tests.thresholds

        if verify_pass:
            return watcher.NoneNoReason
        else:
            n_exp_failed = thresholds.failed_exposures_counter
            n_exp_threshold = thresholds.max_number_failed_exposures
            return AlarmSeverity.WARNING, (
                f"cp_verify run {job_id_verify} failed verification threshold. "
                f"{n_exp_failed} exposures failed majority of tests, n_exposure"
                f" threshold: {n_exp_threshold}."
            )

    @dataclass
    class VerificationThresholds:
        """Class contatining verification
        thresholds.
        """

        max_number_failures_per_detector_per_test: int
        max_number_failed_detectors: int
        failure_threshold_exposure: int
        max_number_failed_exposures: int
        failed_exposures_counter: int

    @dataclass
    class VerificationTests:
        """Class for storing the output of
        'count_failed_verification_tests'.
        """

        certify_calib: bool
        total_counter_failed_tests: dict
        thresholds: VerificationThresholds

    def count_failed_verification_tests(
        self, verify_stats, max_number_failures_per_detector_per_test
    ):
        """Count number of tests that failed cp_verify.

        Parameters
        ----------
        verify_stats : `dict`
            Statistics from cp_verify.
        max_number_failures_per_detector_per_test : `int`
            Maximum number of verification tests per detector per
            exposure per test type that are tolerated in order to
            certify the combined calibration.

        Returns
        -------
        verification_tests : `VerificationTests dataclass`
            Dataclass containing:
            certify_calib : `bool`
                Boolean assessing whether the calibration should be certified.
            total_counter_failed_tests : `dict`[`str`][`str`] or `None`.
                Dictionary with the total number of tests failed per exposure
                and per cp_verify test type. If there are not any tests that
                failed, `None` will be returned.
            thresholds : `VerificationThresholds dataclass`
                Dataclass reporting the different thresholds used to decide
                whether a calibration should be certified or not (see `Notes`
                below). If there are not any tests that failed,
                `None` will be returned.

        Notes
        -----
        For at least one type of test, if the majority of tests fail in
        the majority of detectors and the majority of exposures,
        then don't certify the calibration.
        """
        certify_calib = True

        # Thresholds
        # Main key of verify_stats is exposure IDs
        max_number_failed_exposures = int(len(verify_stats) / 2) + 1  # majority of exps

        max_number_failed_detectors = (
            int(self.n_detectors / 2) + 1
        )  # majority of detectors

        # Define failure threshold per exposure
        failure_threshold_exposure = (
            max_number_failures_per_detector_per_test * max_number_failed_detectors
        )

        # Count the number of failures per test per exposure.
        total_counter_failed_tests = {}
        for exposure in [key for key in verify_stats if key != "SUCCESS"]:
            if "FAILURES" in verify_stats[exposure]:
                # Gather the names of the types of tests that failed.
                # 'stg' is of the form e.g., 'R22_S21 C17 NOISE' or
                # 'R22_S22 SCATTER', so we retreive the name of the test from
                # the last element after splitting it.
                fail_count = [
                    stg.split(" ")[-1] for stg in verify_stats[exposure]["FAILURES"]
                ]
                counter = collections.defaultdict(lambda: 0)
                for test in fail_count:
                    counter[test] += 1
                total_counter_failed_tests[exposure] = counter
            else:
                continue

        # If there are not exposures with tests that failed.
        if len(total_counter_failed_tests) == 0:
            return certify_calib, None, None

        # Count the number of exposures where a given test fails
        # in the majority of detectors.
        failed_exposures_counter = 0
        for exposure in total_counter_failed_tests:
            for test in total_counter_failed_tests[exposure]:
                if (
                    total_counter_failed_tests[exposure][test]
                    >= failure_threshold_exposure
                ):
                    failed_exposures_counter += 1
                    # Exit the inner loop over tests: just need
                    # the condition to be satisfied for
                    # at least one type of test
                    break

        # For at least one type of test, if the majority of tests fail in
        # the majority of detectors and the majority of exposures,
        # then don't certify the calibration
        if failed_exposures_counter >= max_number_failed_exposures:
            certify_calib = False

        # Return a dataclass with the thresholds to report
        # them if verification fails.
        thresholds = self.VerificationThresholds(
            max_number_failures_per_detector_per_test,
            max_number_failed_detectors,
            failure_threshold_exposure,
            max_number_failed_exposures,
            failed_exposures_counter,
        )
        verification_tests = self.VerificationTests(
            certify_calib, total_counter_failed_tests, thresholds
        )
        return verification_tests

    def get_cp_verify_stats(self, response_verify):
        """Get cp_verify statistics from the butler.

        Parameters
        ----------
        response_verify : `dict`
            OCPS call response.

        Returns
        -------
        verify_stats : `dict`
            Statistics from cp_verify.
        """
        job_id_verify = response_verify["job_id"]
        # Loop over the entries of the 'results' list
        # and look for the adecuate dataset type.
        verify_stats_string = None
        for entry in response_verify["results"]:
            uri = entry["uri"]
            for substr in ("verifyBiasStats", "verifyDarkStats", "verifyFlatStats"):
                if substr in uri:
                    verify_stats_string = substr
                    break
        if verify_stats_string is None:
            # This is not a response from cp_verify
            # bias, dark, or flat.
            raise salobj.ExpectedError(
                f"Job {job_id_verify} is not a recognizable cp_verify run."
            )

        # Find repo and instrument
        if len(response_verify["parameters"]["environment"]):
            raise salobj.ExpectedError(
                "response_verify['parameters']['environment'] is empty."
            )

        for entry in response_verify["parameters"]["environment"]:
            if entry["name"] == "BUTLER_REPO":
                repo = entry["value"]
                instrument_name = repo.split("/")[-1]
                break
            else:
                raise salobj.ExpectedError("OCPS response does not list a repo.")

        # Collection name containing the verification outputs.
        verify_collection = f"u/ocps/{job_id_verify}"

        loop = asyncio.get_running_loop()
        butler = await loop.run_in_executor(
            None,
            functools.partial(dafButler.Butler, repo, collections=[verify_collection]),
        )

        loop = asyncio.get_running_loop()
        verify_stats = await loop.run_in_executor(
            None,
            functools.partial(
                butler.get, repo, verify_stats_string, instrument=instrument_name
            ),
        )

        return verify_stats