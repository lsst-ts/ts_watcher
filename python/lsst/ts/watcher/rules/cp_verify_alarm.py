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
                ocps_index:
                    OCPS index (e.g., OCPS:1: LATISS; OCPS:2: LSSTComCam).
                verification_threshold:
                    type: integer
                    descriptor: Maximum number of failures per detector per test type.
                default: 8
            required: [calibration_type, ocps_index]
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    def __call__(self, topic_callback):
        msg = topic_callback.get()
        # OCPS response after calling the pipetask
        response = json.loads(msg.result)
        # Get the dictionary with cp_verify stats, from the butler.
        verify_stats = await self.get_cp_verify_stats(response)
        # boolean: did verification fail?
        return await self.check_response(response, verify_stats)

    async def check_response(self, response_verify, verify_stats):
        """Determine if cp_verify tests passed from OCPS response.

        Parameters
        ----------
        response_verify : `dict`
            OCPS call response.

        verify_stats: `dict`
            Dictionary with statistics after running ``cp_verify``.

        Returns
        -------
        AlarmSeverity : `lsst.ts.idl.enums.Watcher`
            Alarm severity.
        reason : `str`
            Reason for the alarm severity.
        """
        verify_pass = True
        job_id_verify = response_verify["job_id"]

        if verify_stats["SUCCESS"] is False:
            (verify_pass, _, thresholds,) = await self.count_failed_verification_tests(
                verify_stats, self.config.verification_threshold
            )

        if verify_pass:
            return watcher.NoneNoReason
        else:
            n_exp_failed = thresholds["FINAL_NUMBER_OF_FAILED_EXPOSURES"]
            n_exp_threshold = thresholds["MAX_FAILED_EXPOSURES_THRESHOLD"]
            return AlarmSeverity.WARNING, (
                f"cp_verify run {job_id_verify} failed verification threshold. "
                f"{n_exp_failed} exposures failed majority of tests, n_exposure"
                f" threshold: {n_exp_threshold}."
            )

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

    async def get_cp_verify_stats(self, response_verify):
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
        for entry in response_verify["results"]:
            if "verifyBiasStats" in entry["uri"]:
                verify_stats_string = "verifyBiasStats"
                break
            elif "verifyDarkStats" in entry["uri"]:
                verify_stats_string = "verifyDarkStats"
                break
            elif "verifyFlatStats" in entry["uri"]:
                verify_stats_string = "verifyFlatStats"
                break
            else:
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
        butler = dafButler.Butler(repo, collections=[verify_collection])
        verify_stats = butler.get(verify_stats_string, instrument=instrument_name)

        return verify_stats
