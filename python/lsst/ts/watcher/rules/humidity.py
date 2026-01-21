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

__all__ = ["Humidity"]

import yaml

from lsst.ts import utils

from ..base_ess_rule import BaseEssRule


class Humidity(BaseEssRule):
    """Check the humidity.

    This rule only reads ESS telemetry topics.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
    log : `logging.Logger`, optional
        Parent logger.

    Notes
    -----
    The alarm name is f"Humidity.{name}".

    Like most rules based on data from the ESS CSC: this uses
    `FilteredTopicField` and its ilk, because a given topic may be output
    for more than one sensor (e.g. there may be two humidity sensors
    or two 4-channel temperature sensors connected to the same CSC)
    where the data is differentiated by the value of the sensorName field.
    """

    def __init__(self, config, log=None):
        self.poll_loop_task = utils.make_done_future()

        super().__init__(
            config=config,
            name=f"Humidity.{config.name}",
            topic_attr_name="tel_relativeHumidity",
            field_name="relativeHumidityItem",
            sensor_info_name="humidity_sensors",
            is_indexed=False,
            big_is_bad=True,
            units="%",
            value_format="0.2f",
            log=log,
        )

    @classmethod
    def get_schema(cls):
        schema_yaml = """
$schema: http://json-schema.org/draft-07/schema#
description: >-
    Configuration for Humidity rule.
    A typical warning level is 73%. It is unusual to have a closing limit.
type: object
properties:
  name:
    description: Telescope being monitored, typically AuxTel or MainTel.
    type: string
  humidity_sensors:
    description: ESS humidity sensors to monitor.
    type: array
    minItems: 1
    items:
      type: object
      properties:
        sal_index:
          description: SAL index of ESS CSC.
          type: integer
        sensor_names:
          description: >-
            Values of sensorName field to read for the relativeHumidity
            telemetry topic.
          type: array
          minItems: 1
          items:
            type: string
      required:
        - sal_index
        - sensor_names
      additionalProperties: false
  warning_level:
    description: >-
        The relative humidity (%) above which a warning alarm is issued.
        Omit for no such alarm.
    type: number
  serious_level:
    description: >-
        The relative humidity (%) above which a serious alarm is issued.
        Omit for no such alarm.
    type: number
  critical_level:
    description: >-
        The relative humidity (%) above which a serious alarm is issued.
        Omit for no serious alarm.
    type: number
  warning_period:
    description: >-
        The time period [s] after which the warning alarm is raised.
    type: number
    default: 0
  serious_period:
    description: >-
        The time period [s] after which the serious alarm is raised.
    type: number
    default: 0
  critical_period:
    description: >-
        The time period [s] after which the critical alarm is raised.
    type: number
    default: 0
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
        The amount by which relative humidity (%) must decrease below
        a severity level before alarm severity is decreased.
    type: number
    default: 0.5
  poll_interval:
    description: Time delay between polling updates (second).
    type: number
    default: 60
  max_data_age:
    description: >-
      Maximum age of data that will be used (seconds). If all
      humidity data is older than this, go to SERIOUS severity.
    type: number
    default: 120
required:
  - name
  - humidity_sensors
  - hysteresis
  - poll_interval
  - max_data_age
additionalProperties: false
       """
        return yaml.safe_load(schema_yaml)
