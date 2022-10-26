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

__all__ = ["CpVerifyBiasAlarm"]

import yaml
import json
import lsst.daf.butler as dafButler

from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts import watcher


class CpVerifyBiasAlarm(watcher.BaseRule):
    """Report if cp_verify BIAS tests failed.

    Set alarm severity NONE if the cp_verify tests passed,
    and issue a WARNING if not.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.

    Notes
    -----
    The alarm name is f"CpVerifyBiasAlarm.{name}:{index}",
    where name and index are derived from ``config.name``.
    """

    def __init__(self, config):
        remote_name = "OCPS"
        # remote_index = 0: process events from both OCPS's
        remote_index = 0
        remote_info = watcher.RemoteInfo(
            name=remote_name,
            index=remote_index,
            callback_names=["job_result"],
            poll_names=[],
        )
        super().__init__(
            config=config,
            name=f"CpVerifyBiasAlarm.{remote_info.name}:{remote_info.index}",
            remote_info_list=[remote_info],
        )

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            description: Configuration for CpVerifyBiasAlarm
            type: object
            properties:
                name:
                    description: >-
                        CSC name and index in the form `name` or `name:index`.
                        The default index is 0.
                    type: string
                number_verification_tests_threshold_bias:
                    type: integer
                    descriptor: Minimum number of verification tests per detector per exposure per \
                        test type that should pass to certify the bias combined calibration.
                default: 8
            required: [name]
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    def __call__(self, topic_callback):
        msg = topic_callback.get()
        # OCPS response after calling the pipetask
        response = json.loads(msg.result)
        # boolean: did bias verification fail?
        verify_bias_tests_pass = await self.get_verify_tests_pass_boolean(response)

        if verify_bias_tests_pass:
            return watcher.NoneNoReason
        else:
            # Tests did not pass. Follow up on images and calibrations is
            # recommended.
            return AlarmSeverity.SERIOUS, "FAULT state"

    async def get_verify_tests_pass_boolean(self, response_verify):
        """Determine if cp_verify bias tests passed from OCPS response.

        Parameters
        ----------
        response : `dict`

        Returns
        -------
        verify_bias_pass : `bool`
            Did the cp_verify bias test pass?
        """
        verify_bias_pass = True
        # Loop over the entries of the 'results' list
        # and look for the adecuate dataset type.
        for entry in response_verify["results"]:
            if "verifyBiasStats" in entry["uri"]:
                verify_stats_string = "verifyBiasStats"
                break
            else:
                # This is not a response from cp_verify bias.
                # Do not issue a watcher alarm
                return verify_bias_pass

        # Find repo and instrument
        for entry in response_verify["parameters"]["environment"]:
            if entry["name"] == "BUTLER_REPO":
                repo = entry["value"]
                instrument_name = repo.split("/")[-1]
                break

        if verify_stats_string:
            job_id_verify = response_verify["job_id"]
            # Collection name containing the verification outputs.
            verify_collection = f"u/ocps/{job_id_verify}"
            butler = dafButler.Butler(repo, collections=[verify_collection])
            verify_stats = butler.get(verify_stats_string, instrument=instrument_name)
            if verify_stats["SUCCESS"] is False:
                (verify_bias_pass, _, _,) = await self.count_failed_verification_tests(
                    verify_stats, self.config.number_verification_tests_threshold_bias
                )
            else:
                # Nothing failed
                verify_bias_pass = True

        return verify_bias_pass

    async def count_failed_verification_tests(
        self, verify_stats, max_number_failures_per_detector_per_test
    ):
        """Count number of tests that failed cp_verify.

        Parameters
        ----------
        verify_stats : `dict`
            Statistics from cp_verify.
        max_number_failures_per_detector_per_test : `int`
            Minimum number of verification tests per detector per
            exposure per test type that should pass to certify the
            combined calibration.

        Returns
        -------
        certify_calib : `bool`
            Boolean assessing whether the calibration should be certified.
        total_counter_failed_tests : `dict`[`str`][`str`] or `None`.
            Dictionary with the total number of tests failed per exposure and
            per cp_verify test type. If there are not any tests that failed,
            `None` will be returned.
        thresholds : `dict`[`str`][`int`] or `None`
            Dictionary reporting the different thresholds used to decide
            whether a calibration should be certified or not (see `Notes`
            below). If there are not any tests that failed,
            `None` will be returned.

        Notes
        -----
        For at least one type of test, if the majority of tests fail in
        the majority of detectors and the majority of exposures,
        then don't certify the calibration.

        Suported calibrations: see `self.pipetask_parameters_verification`.
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
                counter = {}
                for test in fail_count:
                    if test in counter:
                        counter[test] += 1
                    else:
                        counter[test] = 1
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

        # Return a dictionary with the thresholds to report
        # them if verification fails.
        thresholds = {
            "MAX_FAILURES_PER_DETECTOR_PER_TEST_TYPE_THRESHOLD": max_number_failures_per_detector_per_test,
            "MAX_FAILED_DETECTORS_THRESHOLD": max_number_failed_detectors,
            "MAX_FAILED_TESTS_PER_EXPOSURE_THRESHOLD": failure_threshold_exposure,
            "MAX_FAILED_EXPOSURES_THRESHOLD": max_number_failed_exposures,
            "FINAL_NUMBER_OF_FAILED_EXPOSURES": failed_exposures_counter,
        }

        return certify_calib, total_counter_failed_tests, thresholds
