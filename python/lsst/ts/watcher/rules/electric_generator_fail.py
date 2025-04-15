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

__all__ = ["ElectricGeneratorFail"]

import typing

import yaml
from lsst.ts import salobj
from lsst.ts.xml.enums.Watcher import AlarmSeverity

from ..base_rule import AlarmSeverityReasonType, BaseRule, NoneNoReason
from ..remote_info import RemoteInfo


class ElectricGeneratorFail(BaseRule):
    """Monitor the electric generators (ESS_agcGenset150)
    for any alarming states.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
    log : `logging.Logger`, optional
        Parent logger.
    """

    def __init__(self, config, log=None):
        remote_name_master, remote_index_master = salobj.name_to_name_index(
            config.name_master
        )
        remote_name_slave, remote_index_slave = salobj.name_to_name_index(
            config.name_slave
        )

        self._remote_name_master = remote_name_master
        self._remote_index_master = remote_index_master
        self._remote_name_slave = remote_name_slave
        self._remote_index_slave = remote_index_slave

        remote_info_list = [
            RemoteInfo(
                name=remote_name_master,
                index=remote_index_master,
                callback_names=["tel_agcGenset150"],
                poll_names=[],
            ),
            RemoteInfo(
                name=remote_name_slave,
                index=remote_index_slave,
                callback_names=["tel_agcGenset150"],
                poll_names=[],
            ),
        ]
        super().__init__(
            config=config,
            name="ElectricGeneratorFail",
            remote_info_list=remote_info_list,
            log=log,
        )
        self._master_main_failure = False
        self._slave_main_failure = False

    @classmethod
    def get_schema(cls):
        indent = " " * 8
        severity_values = "\n".join(
            [f"{indent}- {severity.name}" for severity in AlarmSeverity]
        )
        schema_yaml = f"""
$schema: http://json-schema.org/draft-07/schema#
description: >-
    Configuration for electric generators running monitoring.
type: object
properties:
    name_master:
        description: >-
            CSC name and index in the form `name:index`
            for the master electric generator.
        type: string
    name_slave:
        description: >-
            CSC name and index in the form `name:index`
            for the slave electric generator.
        type: string
    severity_individual_fail:
        description: >-
            Alarm severity for when a electric generator has
            a main failure.
        type: string
        default: {AlarmSeverity.SERIOUS.name}
        enum:
{severity_values}
    severity_both_fail:
        description: >-
            Alarm severity for when both electric generators
            have a main failure.
        type: string
        default: {AlarmSeverity.CRITICAL.name}
        enum:
{severity_values}
required:
  - name_master
  - name_slave
additionalProperties: false
       """
        return yaml.safe_load(schema_yaml)

    def compute_alarm_severity(
        self, data: salobj.BaseMsgType, **kwargs: typing.Any
    ) -> AlarmSeverityReasonType:
        """Compute and set alarm severity and reason.

        Parameters
        ----------
        data : `salobj.BaseMsgType`
              Message from the topic described by topic_callback.
        **kwargs : `dict` [`str`, `typing.Any`]
            Keyword arguments. If triggered by `TopicCallback` calling
            `update_alarm_severity`, the arguments will be as follows:

            * topic_callback : `TopicCallback`
              Topic callback wrapper.

        Returns
        -------
        None, if no change or unknown, or a tuple of two values:

        severity: `lsst.ts.xml.enums.Watcher.AlarmSeverity`
            The new alarm severity.
        reason : `str`
            Detailed reason for the severity, e.g. a string describing
            what value is out of range, and what the range is.
            If ``severity`` is ``NONE`` then this value is ignored (but still
            required) and the old reason is retained until the alarm is reset
            to ``nominal`` state.

        Notes
        -----
        You may return `NoneNoReason` if the alarm state is ``NONE``.
        """
        severity, reason = NoneNoReason

        genset_master_failure = getattr(data, "mainFailure")

        if genset_master_failure is True:
            if self._remote_index_master == data.salIndex:
                self._master_main_failure = True
                remote_name = self._remote_name_master
                remote_index = self._remote_index_master
            elif self._remote_index_slave == data.salIndex:
                self._slave_main_failure = True
                remote_name = self._remote_name_slave
                remote_index = self._remote_index_slave

            reason = f"{remote_name}:{remote_index} electric generator main failure."
            severity = AlarmSeverity(int(self.config.severity_individual_fail))

        if self._master_main_failure and self._slave_main_failure:
            reason = "Both electric generator in main failure."
            severity = AlarmSeverity(int(self.config.severity_both_fail))

        return severity, reason
