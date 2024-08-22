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

__all__ = ["PowerOutage"]

import math
import typing

import yaml
from lsst.ts import salobj, utils
from lsst.ts.xml.enums.Watcher import AlarmSeverity

from ..base_rule import AlarmSeverityReasonType, BaseRule, NoneNoReason
from ..remote_info import RemoteInfo

POWER_OUTAGE_REASON = "Power outage detected."
GENERATOR_STARTING_REASON = POWER_OUTAGE_REASON + " The generator is starting."


class PowerOutage(BaseRule):
    """Monitor the PDUs for signs of a power outage.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
    log : `logging.Logger`, optional
        Parent logger.
    """

    def __init__(self, config, log=None):
        remote_name, remote_index = salobj.name_to_name_index(config.name)
        remote_info_list = [
            RemoteInfo(
                name=remote_name,
                index=remote_index,
                callback_names=["tel_scheiderPm5xxx"],
                poll_names=[],
            ),
            RemoteInfo(
                name=remote_name,
                index=remote_index,
                callback_names=["tel_xups"],
                poll_names=[],
            ),
        ]
        super().__init__(
            config=config,
            name=f"PowerOutage.{remote_name}:{remote_index}",
            remote_info_list=remote_info_list,
            log=log,
        )

        self.num_zeros_schneider = 0
        self.xups_alert_started = False
        self.schneider_warn_start_time = 0.0
        self.xups_warn_start_time = 0.0

    @classmethod
    def get_schema(cls):
        schema_yaml = """
$schema: http://json-schema.org/draft-07/schema#
description: >-
    Configuration for UPS power outage monitoring.
type: object
properties:
    name:
        description: >-
            CSC name and index in the form `name` or `name:index`.
            The default index is 0.
        type: string
    min_num_zeros_schneider:
        description: >-
            The number of consecutive zeros before an alarm is raised.
        type: number
    generator_startup_time:
        description: >-
            The number of seconds the power generator needs to start up.
        type: number
required:
  - name
  - min_num_zeros_schneider
  - generator_startup_time
additionalProperties: false
       """
        return yaml.safe_load(schema_yaml)

    def compute_alarm_severity(
        self, data: salobj.BaseMsgType, **kwargs: typing.Any
    ) -> AlarmSeverityReasonType:
        severity, reason = NoneNoReason
        if hasattr(data, "activePowerA"):
            # Schneider UPS.
            if (
                math.isclose(data.activePowerA, 0.0)
                and math.isclose(data.activePowerB, 0.0)
                and math.isclose(data.activePowerC, 0.0)
            ):
                if self.num_zeros_schneider == 0:
                    self.schneider_warn_start_time = utils.current_tai()
                self.num_zeros_schneider += 1
            else:
                self.num_zeros_schneider = 0
            severity, reason = self.determine_schneider_severity_and_reason()

        elif hasattr(data, "inputPower"):
            # Eaton XUPS.
            if (
                math.isnan(data.inputPower[0])
                and math.isnan(data.inputPower[1])
                and math.isnan(data.inputPower[2])
            ):
                if not self.xups_alert_started:
                    self.xups_warn_start_time = utils.current_tai()
                    self.xups_alert_started = True
                severity, reason = self.determine_ups_severity_and_reason(
                    self.xups_warn_start_time
                )

        return severity, reason

    def determine_schneider_severity_and_reason(self):
        severity, reason = NoneNoReason
        if self.num_zeros_schneider >= self.config.min_num_zeros_schneider:
            severity, reason = self.determine_ups_severity_and_reason(
                self.schneider_warn_start_time
            )
        return severity, reason

    def determine_ups_severity_and_reason(self, start_time: float):
        severity, reason = NoneNoReason
        if utils.current_tai() - start_time >= self.config.generator_startup_time:
            severity = AlarmSeverity.CRITICAL
            reason = POWER_OUTAGE_REASON
        else:
            severity = AlarmSeverity.WARNING
            reason = GENERATOR_STARTING_REASON
        return severity, reason
