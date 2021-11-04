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

__all__ = ["DewPointDepression"]

import asyncio
import itertools
import yaml

from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts import utils
from lsst.ts import watcher

# Name of dew point field in ESS telemetry topics
# for dew point and humidity sensors.
ESSDewPointField = "dewPoint"

# Name of temperature field in ESS telemetry topics for humidity sensors.
ESSTemperatureField = "temperature"


class DewPointDepression(watcher.BaseRule):
    """Check the dew point depression.

    This rule only reads ES telemetry topics.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.

    Notes
    -----
    The alarm name is f"DewPointDepression.{name}".

    Like most rules based on data from the ESS CSC: this uses
    `FilteredTopicField` and its ilk, because a given topic may be output
    for more than one sensor (e.g. there may be two humidity sensors
    or two 4-channel temperature sensors connected to the same CSC)
    where the data is differentiated by the value of the sensorName field.
    """

    def __init__(self, config):
        self.poll_loop_task = utils.make_done_future()

        # Dew point field wrappers; computed in `setup`.
        self.dew_point_field_wrappers = watcher.FieldWrapperList()

        # Temperature field wrappers; computed in `setup`.
        self.temperature_field_wrappers = watcher.FieldWrapperList()

        self.threshold_handler = watcher.ThresholdHandler(
            warning_level=getattr(config, "warning_level", None),
            serious_level=getattr(config, "serious_level", None),
            critical_level=getattr(config, "critical_level", None),
            warning_msg="Check for condensation",
            serious_msg="Close the dome",
            critical_msg="Close the dome",
            hysteresis=config.hysteresis,
            big_is_bad=False,
            value_name="dew point",
            units="C",
            value_format="0.2f",
        )

        # Compute dict of (sal_name, sal_index): list of topic attribute names,
        # in order to creat remote_info_list
        topic_names_dict = dict()
        sal_name = "ESS"
        for sensor_info in itertools.chain(
            config.dew_point_sensors, config.temperature_sensors
        ):
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
                index=index,
                callback_names=None,
                poll_names=topic_attr_names,
            )
            for (name, index), topic_attr_names in topic_names_dict.items()
        ]
        super().__init__(
            config=config,
            name=f"DewPointDepression.{config.name}",
            remote_info_list=remote_info_list,
        )

    @classmethod
    def get_schema(cls):
        schema_yaml = """
$schema: http://json-schema.org/draft-07/schema#
description: >-
    Configuration for DewPointDepression rule.
    A typical closure limit is 2 C. A typical warning level is 3 C.
type: object
properties:
  name:
    description: Telescope being monitored, typically AuxTel or MainTel.
    type: string
  dew_point_sensors:
    description: >-
        ESS dew point and humidity sensors to monitor.
        These can be any topic with a "dewPoint" field,
        including hx85a and hx85ba.
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
                    Name of ESS dew point or humidity telemetry topic.
                    Typically "hx85a" or "hx85ba".
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
  temperature_sensors:
    description: >-
        ESS temperature sensors to monitor.
        These can be any topic with a "temperature" field,
        including temperature, hx85a and hx85ba.
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
                    Typically "temperature", "hx85a", or "hx85ba".
                type: string
              sensor_names:
                description: List of dict of sensor_name, indices.
                type: array
                minItems: 1
                items:
                  type: object
                  properties:
                    sensor_name:
                      description: value of sensorName field.
                      type: string
                    indices:
                      description: >-
                        Indices of the data to read (optional).
                        If omitted then read all non-nan values.
                        Must be omitted if the field is a scalar.
                      type: array
                      items:
                        type: integer
                  required:
                    - sensor_name
                  additionalProperties: false
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
        The dew point depression (temperature - dew point) (C) below which
        a warning alarm is issued.
        Omit for no such alarm.
    type: number
  serious_level:
    description: >-
        The dew point depression (temperature - dew point) (C) below which
        a serious alarm is issued.
        Omit for no such alarm.
    type: number
  critical_level:
    description: >-
        The dew point depression (temperature - dew point) (C) below which
        a critical alarm is issued.
        Omit for no such alarm.
    type: number
  hysteresis:
    description: >-
        The amount by which temperature - dewPoint (C) must increase above
        a severity level before alarm severity is decreased.
    type: number
    default: 0.2
  poll_interval:
    description: Time delay between polling updates (second).
    type: number
    default: 60
  max_data_age:
    description: >-
      Maximum age of data that will be used (seconds). If all dew point or all
      temperature data is older than this, go to SERIOUS severity.
    type: number
    default: 120
required:
  - name
  - dew_point_sensors
  - temperature_sensors
  - hysteresis
  - poll_interval
  - max_data_age
additionalProperties: false
       """
        return yaml.safe_load(schema_yaml)

    def setup(self, model):
        """Create filtered topic wrappers."""
        sal_name = "ESS"
        for dew_point_sensor_info in self.config.dew_point_sensors:
            sal_index = dew_point_sensor_info["sal_index"]
            remote = model.remotes[(sal_name, sal_index)]
            for topic_info in dew_point_sensor_info["topics"]:
                topic_attr_name = "tel_" + topic_info["topic_name"]
                topic = getattr(remote, topic_attr_name)

                for sensor_name in topic_info["sensor_names"]:
                    field_wrapper = watcher.FilteredEssFieldWrapper(
                        model=model,
                        topic=topic,
                        sensor_name=sensor_name,
                        field_name=ESSDewPointField,
                    )
                    self.dew_point_field_wrappers.add_wrapper(field_wrapper)

        for temperature_sensor_info in self.config.temperature_sensors:
            sal_index = temperature_sensor_info["sal_index"]
            remote = model.remotes[(sal_name, sal_index)]
            for topic_info in temperature_sensor_info["topics"]:
                topic_attr_name = "tel_" + topic_info["topic_name"]
                topic = getattr(remote, topic_attr_name)

                for sensor_field_name in topic_info["sensor_names"]:
                    sensor_name = sensor_field_name["sensor_name"]
                    indices = sensor_field_name.get("indices", None)
                    if indices is not None:
                        field_wrapper = watcher.IndexedFilteredEssFieldWrapper(
                            model=model,
                            topic=topic,
                            sensor_name=sensor_name,
                            field_name=ESSTemperatureField,
                            indices=indices,
                        )
                    else:
                        field_wrapper = watcher.FilteredEssFieldWrapper(
                            model=model,
                            topic=topic,
                            sensor_name=sensor_name,
                            field_name=ESSTemperatureField,
                        )
                    self.temperature_field_wrappers.add_wrapper(field_wrapper)

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
            self.alarm.set_severity(severity=severity, reason=reason)
            await asyncio.sleep(self.config.poll_interval)

    def __call__(self, topic_callback=None):
        current_tai = utils.current_tai()
        # List of (dew_point, wrapper, index)
        dew_points = self.dew_point_field_wrappers.get_data(
            max_age=self.config.max_data_age
        )
        # List of (temperature, wrapper, index)
        temperatures = self.temperature_field_wrappers.get_data(
            max_age=self.config.max_data_age
        )
        if not dew_points or not temperatures:
            poll_duration = current_tai - self.poll_start_tai
            if poll_duration > self.config.max_data_age:
                missing_strs = []
                if not dew_points:
                    missing_strs.append("dew point")
                if not temperatures:
                    missing_strs.append("temperature")
                missing_data = " or ".join(missing_strs)
                return (
                    AlarmSeverity.SERIOUS,
                    f"No {missing_data} data seen for at least {self.config.max_data_age} seconds",
                )
            else:
                # We have not been polling long enough to complain
                return watcher.NoneNoReason

        # We got data; use the most pessimistic measured value.
        max_dew_point, dew_point_wrapper, dew_point_index = max(
            dew_points, key=lambda v: v[0]
        )
        min_temperature, temperature_wrapper, temperature_index = min(
            temperatures, key=lambda v: v[0]
        )
        dew_point_depression = min_temperature - max_dew_point

        source_descr = (
            f"{dew_point_wrapper.get_value_descr(dew_point_index)} and "
            f"{temperature_wrapper.get_value_descr(temperature_index)}"
        )
        return self.threshold_handler.get_severity_reason(
            value=dew_point_depression,
            current_severity=self.alarm.severity,
            source_descr=source_descr,
        )
