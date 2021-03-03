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

__all__ = ["CONFIG_SCHEMA"]

import yaml

CONFIG_SCHEMA = yaml.safe_load(
    """
$schema: http://json-schema.org/draft-07/schema#
$id: https://github.com/lsst-ts/ts_watcher/python/lsst/ts/Watcher/config_schema.py
title: Watcher v1
description: Configuration for the Watcher
type: object
# Do not require disabled_sal_components and other properties with defaults
# to avoid failed validation.
required: [rules]
additionalProperties: false
properties:
  disabled_sal_components:
    description: >-
      Names of SAL components that the Watcher will ignored.
      The format is component_name:index where :index is optional if the index is 0.
    type: array
    default: []
    items:
      type: string
  auto_acknowledge_delay:
    description: >-
      Delay (in seconds) before a stale alarm is automatically acknowledged,
      or 0 for no automatic acknowledgement.
      A stale alarm is one that has not yet been acknowledged, but its
      severity has gone to NONE.
    type: number
    default: 3600
  auto_unacknowledge_delay:
    description: >-
      Delay (in seconds) before an acknowledged alarm is automatically
      unacknowledged, or 0 for no automatic unacknowledgement.
      Automatic unacknowledgement only occurs if the alarm persists,
      because an acknowledged alarm is reset if the severity goes to NONE.
    type: number
    default: 3600
  rules:
    description: Rules and rule configuration.
    type: array
    items:
      type: object
      required: [classname, configs]
      additionalProperties: false
      properties:
        classname:
          description: >-
            Name of rule class, e.g. Heartbeat.
            If the class is in a subdirectory of "rules",
            separate the fields with a period, e.g. at.AnAuxTelRule.
          type: string
        configs:
          description: >-
            Configuration for each instance of the rule.
            The data will be validated against the rule's schema.
            Use a pair of curly braces for an empty config.
          type: array
          minItems: 1
          items:
            type: object
  escalation:
    description: >-
      Alarm escalation configuration. Alarms are escalated if their max severity is critical
      and they have not been acknowledged within a specified period.
      Note that they are escalated even if they are stale.
      Each alarm matches at most one entry in this list: the first match is used.
    type: array
    default: []
    items:
      type: object
      required: [alarms, to, delay]
      additionalProperties: false
      minItems: 0
      properties:
        alarms:
          description: >-
            Alarms to which this escalation configuration applies,
            specified as a list of case-blind glob expressions.
            Each expression must match the full alarm name in order for
            the escalation configuration to apply to that alarm.
          type: array
          minItems: 1
          items:
            type: string
        to:
          description: >-
            User or channel to which to escalate these alarms.
            Set empty to prevent this alarm from being escalated
            (as if the alarm did not appear in the escalation section).
          type: string
        delay:
          description: >-
            Delay before escalating these alarms (seconds).
            A value of 0 disables escalation (as does an empty string for `to`).
            The alarm will be escalated `delay` seconds after the alarm severity
            first goes to CRITICAL, unless the alarm is acknowledged first.
            Warning: stale alarms–those for which the severity has gone back to None–
            will not reliably be escalated if `delay` is longer than `auto_acknowledge_delay`,
            because the alarm may be automatically acknowledged before it is escalated.
          type: number
"""
)
