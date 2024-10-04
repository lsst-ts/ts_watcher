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

__all__ = ["Hvac"]

import dataclasses
import enum
import math
import typing

import yaml
from lsst.ts import salobj, utils
from lsst.ts.xml.enums.Watcher import AlarmSeverity

from ..base_rule import AlarmSeverityReasonType, BaseRule, NoneNoReason
from ..remote_info import RemoteInfo

SLEEP_TIME = 1.0


class LimitType(enum.StrEnum):
    """Limit type."""

    lower = "lower"
    upper = "upper"


@dataclasses.dataclass
class AlarmInfo:
    """Alarm info holder.

    Parameters
    ----------
    start_time : `float`
        The TAI start time [unix seconds] of the alarm state.
    time_span : `float`
        The time span the limit needs to be crossed before an alarm is raised.
    severity : `AlarmSeverity`
        The alarm severity.
    reason : `str`
        The reason for the alarm.
    """

    start_time: float
    time_span: float
    severity: AlarmSeverity
    reason: str


class Hvac(BaseRule):
    """Monitor HVAC SAL topics for any alarming states.

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
        remote_name = "HVAC"
        remote_index = 0
        rule_name = config.rule_name
        callback_names = config.callback_names
        remote_info_list = [
            RemoteInfo(
                name=remote_name,
                index=remote_index,
                callback_names=callback_names,
                poll_names=[],
            )
        ]
        super().__init__(
            config=config,
            name=f"{remote_name}.{rule_name}",
            remote_info_list=remote_info_list,
            log=log,
        )

        # Keep track of alarm states.
        self.alarm_info_dict: dict[str, AlarmInfo] = {}

    @classmethod
    def get_schema(cls):
        enum_str = ", ".join(
            f"{severity.name}"
            for severity in AlarmSeverity
            if severity is not AlarmSeverity.NONE
        )
        schema_yaml = f"""
$schema: http://json-schema.org/draft-07/schema#
description: Configuration for HvacDynalene rule.
type: object
properties:
  rule_name:
    description: The names of the rule.
    type: string
  callback_names:
    description: The names of the callbacks, i.e. the SAL topics.
    type: array
    minItems: 1
    items:
      type: string
  individual_limits:
    description: Limits for individual items.
    type: array
    minItems: 1
    items:
      type: object
      properties:
        item_name:
          description: The name of the topic item.
          type: string
        limit_type:
          description: The type of limit.
          type: string
          enum:
          - upper
          - lower
        limit_value:
          description: The value of the limit.
          type: number
        time_span:
          description: >-
            The minimum amount of time [s] for which the limit needs to have
            been passed before an alarm is triggered. If set to 0 s then the
            alarm will be sent immediately.
          type: number
          default: 0
        severity:
          description: Alarm severity.
          type: string
          enum: [{enum_str}]
      required:
        - item_name
        - limit_type
        - limit_value
        - severity
      additionalProperties: false
  difference_limits:
    description: Limits for differences between two items.
    type: array
    minItems: 1
    items:
      type: object
      properties:
        first_item_name:
          description: The name of the first item.
          type: string
        second_item_name:
          description: The name of the second item.
          type: string
        limit_type:
          description: The type of limit (upper or lower).
          type: string
          enum:
          - upper
          - lower
        limit_value:
          description: The value of the limit.
          type: number
        time_span:
          description: >-
            The minimum amount of time [s] for which the limit needs to have
            been passed before an alarm is triggered.
          type: number
          default: 0
        severity:
          description: Alarm severity.
          type: string
          enum: [{enum_str}]
      required:
        - first_item_name
        - second_item_name
        - limit_type
        - limit_value
        - severity
      additionalProperties: false
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
        curr_tai = utils.current_tai()

        if hasattr(self.config, "individual_limits"):
            self._process_individual_limits(data, curr_tai)

        # Do the same for the difference limits.
        if hasattr(self.config, "difference_limits"):
            self._process_difference_limits(data, curr_tai)

        return self._determine_severity_and_reason(curr_tai)

    def _process_individual_limits(
        self, data: salobj.BaseMsgType, curr_tai: float
    ) -> None:
        """Loop over all individual limits and compare the value with the
        limit.

        If the value does not meet the limit criteria, alarm info for no alarm
        is added. Else, if the value does meet the limit criteria, store the
        alarm info if not already stored or if alarm info for no alarm was
        previsouly stored.

        Parameters
        ----------
        data : `salobj.BaseMsgType`
              Message from the topic described by topic_callback.
        curr_tai : `float`
            The current TAI time [unix seconds].
        """
        for individual_limit in self.config.individual_limits:
            item_value = getattr(data, individual_limit["item_name"])
            limit_value = individual_limit["limit_value"]
            limit_type = LimitType(individual_limit["limit_type"])

            limit_crossed = False
            match limit_type:
                case LimitType.upper:
                    limit_crossed = item_value > limit_value
                case LimitType.lower:
                    limit_crossed = item_value < limit_value

            item_name = f"{individual_limit['item_name']} {limit_type}"
            self._add_or_update_alarm_info(
                limit_crossed, item_name, item_value, curr_tai, individual_limit
            )

    def _process_difference_limits(
        self, data: salobj.BaseMsgType, curr_tai: float
    ) -> None:
        """Loop over all difference limits and compare the difference between
        the two items with the limit.

        If the differemnce does not meet the limit criteria and the alarm info
        was stored in `self.alarm_info_dict`, remove it. Else, if the
        difference does meet the limit criteria, store the alarm info if not
        already stored.

        Parameters
        ----------
        data : `salobj.BaseMsgType`
              Message from the topic described by topic_callback.
        curr_tai : `float`
            The current TAI time [unix seconds].
        """
        for difference_limit in self.config.difference_limits:
            first_item_name = difference_limit["first_item_name"]
            first_item_value = getattr(data, difference_limit["first_item_name"])
            second_item_name = difference_limit["second_item_name"]
            second_item_value = getattr(data, difference_limit["second_item_name"])
            limit_value = difference_limit["limit_value"]
            limit_type = LimitType(difference_limit["limit_type"])

            limit_crossed = False
            match limit_type:
                case LimitType.upper:
                    limit_crossed = first_item_value - second_item_value > limit_value
                case LimitType.lower:
                    limit_crossed = first_item_value - second_item_value < limit_value

            item_name = f"{first_item_name} - {second_item_name} {limit_type}"
            item_value = first_item_value - second_item_value
            self._add_or_update_alarm_info(
                limit_crossed, item_name, item_value, curr_tai, difference_limit
            )

    def _add_or_update_alarm_info(
        self,
        limit_crossed: bool,
        item_name: str,
        item_value: float,
        curr_tai: float,
        limit: dict[str, typing.Any],
    ) -> None:
        """Add or update the alarm info for the provided item.

        If no alarm info exists yet in `self.alarm_info_dict`, it gets added.
        If alarm info is present then any of the following can happen:

            - If the limit wasn't crossed then alarm info for no alarm is set
              either if there was alarm info present for the item or not.
            - If the liomit was crossed then

                - If alarm info was not present yet then it is set with the
                  severity from the configuration.
                - If alarm info is present and the severity for that is NONE,
                  it is set with the severity from the configuration.

        Parameters
        ----------
        limit_crossed : `bool`
            Was the limit crossed or not?
        item_name : `str`
            The name of the item.
        item_value : `float`
            The value of the item.
        curr_tai : `float`
            The current TAI time [unix seconds].
        limit : `dict`[`str`, `typing.Any`]
            The limit to apply. This comes from the configuration that is
            loaded when this class is initialized.
        """
        if not limit_crossed:
            self.alarm_info_dict[item_name] = AlarmInfo(
                start_time=math.nan,
                time_span=limit["time_span"],
                severity=AlarmSeverity.NONE,
                reason="",
            )
        elif (
            item_name not in self.alarm_info_dict
            or self.alarm_info_dict[item_name].severity == AlarmSeverity.NONE
        ):
            self.alarm_info_dict[item_name] = AlarmInfo(
                start_time=curr_tai,
                time_span=limit["time_span"],
                severity=AlarmSeverity[limit["severity"]],
                reason=(
                    f"The {item_name} value {item_value} is "
                    f"{'higher' if limit['limit_type'] == 'upper' else 'lower'} "
                    f"than the configured limit {limit['limit_value']}"
                ),
            )

    def _determine_severity_and_reason(
        self, curr_tai: float
    ) -> AlarmSeverityReasonType:
        """Determine the severity and reason.

        Loop over all `self.alarm_info_dict` items and determine the highest
        `AlarmSeverity`. Also concat all reasons to a comma separated string.
        Then return both.

        Parameters
        ----------
        curr_tai : `float`
            The current TAI time [unix seconds].

        Returns
        -------
        severity: `lsst.ts.xml.enums.Watcher.AlarmSeverity`
            The new alarm severity.
        reason : `str`
            A comma separated string containing all alarm reasons, or an empty
            string if no alarm.
        """
        severity, reason = NoneNoReason
        all_reasons = []
        for alarm_state in self.alarm_info_dict:
            alarm_info = self.alarm_info_dict[alarm_state]
            if (
                not math.isnan(alarm_info.start_time)
                and curr_tai - alarm_info.start_time >= alarm_info.time_span
            ):
                severity = max(severity, alarm_info.severity)
                all_reasons.append(alarm_info.reason)

        reason = ", ".join(all_reasons)
        return severity, reason
