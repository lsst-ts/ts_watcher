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

__all__ = ["UnderPressure"]

import yaml

from .base_ess_rule import BaseEssRule


class UnderPressure(BaseEssRule):
    """Check for low pressure.

    This rule only reads ESS telemetry topics.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.

    Notes
    -----
    The alarm name is f"UnderPressure.{name}".

    Like most rules based on data from the ESS CSC: this uses
    `FilteredTopicField` and its ilk, because a given topic may be output
    for more than one sensor (e.g. there may be two pressure sensors
    or two 4-channel pressure sensors connected to the same CSC)
    where the data is differentiated by the value of the sensorName field.
    """

    def __init__(self, config):
        super().__init__(
            config=config,
            rule_name=f"UnderPressure.{config.name}",
            topic_attr_name="tel_pressure",
            field_name="pressure",
            sensor_info_name="pressure_sensors",
            is_indexed=True,
            big_is_bad=False,
            units="Pa",
            value_format="0.2f",
        )

    @classmethod
    def get_schema(cls):
        schema_yaml = """
$schema: http://json-schema.org/draft-07/schema#
description: Configuration for UnderPressure rule.
type: object
properties:
  name:
    description: System being monitored, e.g. "MTM1M3 air pressure".
    type: string
  pressure_sensors:
    description: >-
        ESS pressure sensors to monitor.
        Pressures are reported in the pressure telemetry topic.
    type: array
    minItems: 1
    items:
      type: object
      properties:
        sal_index:
          description: SAL index of ESS CSC.
          type: integer
        sensor_info:
          description: List of dict of sensor_name, indices.
          type: array
          minItems: 1
          items:
            type: object
            properties:
              sensor_name:
                description: Value of sensorName field.
                type: string
              indices:
                description: >-
                  Indices of the data to read (optional).
                  If omitted then read all non-nan values.
                type: array
                items:
                  type: integer
            required:
              - sensor_name
            additionalProperties: false
      required:
        - sal_index
        - sensor_info
      additionalProperties: false
  warning_level:
    description: >-
        The pressure (Pa) below which a warning alarm is issued.
        Omit for no warning alarm.
    type: number
  serious_level:
    description: >-
        The pressure (Pa) below which a serious alarm is issued.
        Omit for no serious alarm.
    type: number
  critical_level:
    description: >-
        The pressure (Pa) below which a critical alarm is issued.
        Omit for no critical alarm.
    type: number
  warning_msg:
    description: >-
        The main message for a warning alarm.
        If omitted the reason will just describe the value and threshold.
    type: string
  serious_msg:
    description: >-
        The main message for a serious alarm.
        If omitted the reason will just describe the value and threshold.
    type: string
  critical_msg:
    description: >-
        The main message for a critical alarm.
        If omitted the reason will just describe the value and threshold.
    type: string
  hysteresis:
    description: >-
        The amount by which pressure (Pa) must decrease below
        a severity level before alarm severity is decreased.
    type: number
    default: 1
  poll_interval:
    description: Time delay between polling updates (second).
    type: number
    default: 60
  max_data_age:
    description: >-
      Maximum age of data that will be used (seconds). If all
      pressure data is older than this, go to SERIOUS severity.
    type: number
    default: 120
required:
  - name
  - pressure_sensors
  - hysteresis
  - poll_interval
  - max_data_age
additionalProperties: false
       """
        return yaml.safe_load(schema_yaml)
