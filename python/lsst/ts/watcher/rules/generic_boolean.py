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

__all__ = ["GenericBoolean"]

import typing

import yaml
from lsst.ts import salobj
from lsst.ts.xml.enums.Watcher import AlarmSeverity

from ..base_rule import AlarmSeverityReasonType, BaseRule, NoneNoReason
from ..remote_info import RemoteInfo


class GenericBoolean(BaseRule):
    """Monitor any SAL topic for any boolean attributes being True or False.

    This is aimed to be a generic rule for any alarm items in events or
    telemetry.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
    rule_name : `str`
        Rule name.
    callback_names : list[`str`]
        Callback names, i.e. SAL topics to which the rule applies.
    log : `logging.Logger`, optional
        Parent logger.
    """

    def __init__(self, config, log=None):
        rule_name = config.rule_name
        remote_name = config.remote_name
        remote_index = config.remote_index
        callback_name = config.callback_name

        csc_name_index = f"{remote_name}:{remote_index}" if remote_index > 0 else remote_name
        remote_info_list = [
            RemoteInfo(
                name=remote_name,
                index=remote_index,
                callback_names=[callback_name],
                poll_names=[],
            )
        ]
        super().__init__(
            config=config,
            name=f"{rule_name}.{csc_name_index}.{callback_name}",
            remote_info_list=remote_info_list,
            log=log,
        )

    @classmethod
    def get_schema(cls):
        enum_str = ", ".join(
            f"{severity.name}" for severity in AlarmSeverity if severity is not AlarmSeverity.NONE
        )
        schema_yaml = f"""
$schema: http://json-schema.org/draft-07/schema#
description: Configuration for GenericBoolean rule.
type: object
properties:
  rule_name:
    description: The name of the Rule.
    type: string
  remote_name:
    description: The name of the Remote.
    type: string
  remote_index:
    description: The index of the Remote.
    type: number
    default: 0
  callback_name:
    description: The name of the callback, i.e. the SAL topic.
    type: string
  alarm_items:
    description: Alarm items in the SAL topic and their alarm values.
    type: array
    minItems: 1
    items:
      type: object
      properties:
        item_name:
          description: The name of the topic item.
          type: string
        alarm_value:
          description: The value that will raise the alarm.
          type: boolean
          default: true
      required:
        - item_name
        - alarm_value
      additionalProperties: false
  severity:
    description: Alarm severity.
    type: string
    enum: [{enum_str}]
required:
  - rule_name
  - remote_name
  - remote_index
  - callback_name
  - alarm_items
  - severity
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

        alarm_reasons = []
        for alarm_item in self.config.alarm_items:
            item_name = alarm_item["item_name"]
            alarm_value = alarm_item["alarm_value"]
            item_value = getattr(data, item_name, False)
            if item_value == alarm_value:
                severity = AlarmSeverity[self.config.severity]
                alarm_reasons.append(f"{alarm_item} is {item_value}")

        if len(alarm_reasons) > 0:
            reason = ",".join(alarm_reasons)
        return severity, reason
