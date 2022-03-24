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

import asyncio
import yaml

from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts import utils
from lsst.ts import watcher

# Name of humidity field in ESS telemetry topics for humidity sensors.
ESSHumidityField = "relativeHumidity"


class Humidity(watcher.BaseRule):
    """Check the humidity.

    This rule only reads ESS telemetry topics.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.

    Notes
    -----
    The alarm name is f"Humidity.{name}".

    Like most rules based on data from the ESS CSC: this uses
    `FilteredTopicField` and its ilk, because a given topic may be output
    for more than one sensor (e.g. there may be two humidity sensors
    or two 4-channel temperature sensors connected to the same CSC)
    where the data is differentiated by the value of the sensorName field.
    """

    def __init__(self, config):
        self.poll_loop_task = utils.make_done_future()

        # Humidity field wrappers; computed in `setup`.
        self.humidity_field_wrappers = watcher.FieldWrapperList()

        self.threshold_handler = watcher.ThresholdHandler(
            warning_level=getattr(config, "warning_level", None),
            serious_level=getattr(config, "serious_level", None),
            critical_level=getattr(config, "critical_level", None),
            hysteresis=config.hysteresis,
            big_is_bad=True,
            value_name="humidity",
            units="%",
            value_format="0.2f",
        )

        # Compute dict of (sal_name, sal_index): list of topic attribute names,
        # in order to creat remote_info_list
        topic_names_dict = dict()
        sal_name = "ESS"
        for sensor_info in config.humidity_sensors:
            sal_index = sensor_info["sal_index"]
            topic_attr_names = [
                "tel_" + topic["topic_name"] for topic in sensor_info["topics"]
            ]
            sal_name_index = (sal_name, sal_index)
            if sal_name_index not in topic_names_dict:
                topic_names_dict[sal_name_index] = topic_attr_names
            else:
                topic_names_dict[sal_name_index] += topic_attr_names

        remote_info_list = [
            watcher.RemoteInfo(
                name=name,
                index=sal_index,
                callback_names=None,
                poll_names=topic_attr_names,
            )
            for (name, sal_index), topic_attr_names in topic_names_dict.items()
        ]
        super().__init__(
            config=config,
            name=f"Humidity.{config.name}",
            remote_info_list=remote_info_list,
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
        topics:
          type: array
          minItems: 1
          items:
            type: object
            properties:
              topic_name:
                description: >-
                    Name of ESS telemetry topic.
                    It must have a relativeHumidity field.
                type: string
              sensor_names:
                description: Values of sensorName field to read.
                type: array
                minItems: 1
                items:
                  type: string
            required:
              - topic_name
              - sensor_names
            additionalProperties: false
      required:
        - sal_index
        - topics
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

    def setup(self, model):
        """Create filtered topic wrappers."""
        sal_name = "ESS"
        for humidity_sensor_info in self.config.humidity_sensors:
            sal_index = humidity_sensor_info["sal_index"]
            sal_name_index = (sal_name, sal_index)
            remote = model.remotes[sal_name_index]
            for topic_info in humidity_sensor_info["topics"]:
                topic_attr_name = "tel_" + topic_info["topic_name"]
                topic = getattr(remote, topic_attr_name)

                for sensor_name in topic_info["sensor_names"]:
                    field_wrapper = watcher.FilteredEssFieldWrapper(
                        model=model,
                        topic=topic,
                        sensor_name=sensor_name,
                        field_name=ESSHumidityField,
                    )
                    self.humidity_field_wrappers.add_wrapper(field_wrapper)

    def start(self):
        self.poll_loop_task.cancel()
        self.poll_loop_task = asyncio.create_task(self.poll_loop())

    def stop(self):
        self.poll_loop_task.cancel()

    async def poll_loop(self):
        # Keep track of when polling begins
        # in order to avoid confusing "no data ever seen"
        # with "all data is older than max_data_age"
        self.poll_start_tai = utils.current_tai()
        while True:
            severity, reason = self()
            await self.alarm.set_severity(severity=severity, reason=reason)
            await asyncio.sleep(self.config.poll_interval)

    def __call__(self, topic_callback=None):
        current_tai = utils.current_tai()
        # List of (humidity, wrapper, index)
        humidity_values = self.humidity_field_wrappers.get_data(
            max_age=self.config.max_data_age
        )
        if not humidity_values:
            poll_duration = current_tai - self.poll_start_tai
            if poll_duration > self.config.max_data_age:
                return (
                    AlarmSeverity.SERIOUS,
                    f"No humidity data seen for {self.config.max_data_age} seconds",
                )
            else:
                return watcher.NoneNoReason

        # We got data; use the most pessimistic measured value.
        humidity, humidity_wrapper, humidity_index = max(
            humidity_values, key=lambda v: v[0]
        )
        source_descr = humidity_wrapper.get_value_descr(humidity_index)
        return self.threshold_handler.get_severity_reason(
            value=humidity,
            current_severity=self.alarm.severity,
            source_descr=source_descr,
        )
