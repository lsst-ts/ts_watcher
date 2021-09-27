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

__all__ = ["DewPointFromHumidityWrapper", "DewPointDepression"]

import asyncio
import functools
import itertools
import math
import yaml

from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts import utils
from lsst.ts import salobj
from lsst.ts import watcher

# ESS topics are filtered by the sensorName field
ESSFilterField = "sensorName"


class DewPointFromHumidityWrapper(watcher.BaseFilteredFieldWrapper):
    """Compute dew point from a sensor that measures humidity and temperature.

    Parameters
    ----------
    model : `Model`
        Watcher model.
    topic : `lsst.ts.salobj.ReadTopic`
        Topic to read. It must have fields ``relativeHumidity``,
        ``temperature`` and ``sensorName``.
        One such topic is ``hx85ba``. Another is ``hx85a``, thought that
        sensor already reports dew point in the ``dewPoint`` field.
    filter_field : `str`
        Name of filter field. Use ESSFilterField for ESS topics.
    filter_value : `str`
        Required value of the ``sensorName`` field.

    Notes
    -----
    Use the `Magnus formula
    <https://github.com/lsst-ts/ts_watcher/blob/develop/doc/Dewpoint_Calculation_Humidity_Sensor_E.pdf>`_:: # noqa

        dp = λ·f / (β - f)

        Where:

        • dp is dew point in deg C
        • β = 17.62
        • λ = 243.12 C
        • f = ln(rh/100) + (β·t)/(λ+t))
        • t = air temperature in deg C
        • rh = relative humidity in %
    """

    def __init__(self, model, topic, filter_field, filter_value):
        super().__init__(
            model=model,
            topic=topic,
            filter_field=filter_field,
            filter_value=filter_value,
            field_descr="dewPointFromHumidity",
        )

    @staticmethod
    def compute_dew_point(relative_humidity, temperature):
        """Compute dew point using the Magnus formula.

        Parameters
        ----------
        relative_humidity : `float`
            Relative humidity (%)
        temperature : `float`
            Air temperature (C)
        """
        β = 17.62
        λ = 243.12
        f = math.log(relative_humidity * 0.01) + β * temperature / (λ + temperature)
        return λ * f / (β - f)

    def update_value(self, data):
        """Compute dew point."""
        self.value = self.compute_dew_point(
            relative_humidity=data.relativeHumidity, temperature=data.temperature
        )

    def _get_nelts(self, data):
        for attr_name in "relativeHumidity", "temperature":
            if not hasattr(data, attr_name):
                raise ValueError(f"Could not find required field {attr_name}")
        return None


class DewPointDepression(watcher.BaseRule):
    """Check the dew point depression.

    Set alarm severity WARNING if dew point depression is near
    the closing limit, and SERIOUS if it is above the closing limit.

    This rule only reads telemetry topics.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.

    Notes
    -----
    The alarm name is f"DewPointDepression.{name}".

    Apache Point Observatory has a dew point depression closure limit of 2 C.
    https://www.apo.nmsu.edu/arc35m/closure_conditions.htm


    Like most rules based on data from the ESS CSC: this uses callbacks
    because a given topic may be output for more than one sensor
    (e.g. there may be two humidity sensors or two 4-channel temperature
    sensors connected to the same CSC) where the data is differentiated
    by the value of the sensorName field. Thus topic.get() is not a safe way
    to get the most current values from a particular sensor.
    Instead use ess topic wrappers
    """

    def __init__(self, config):
        self.poll_loop_task = utils.make_done_future()

        # Dew point field wrappers; computed in `setup`.
        self.dew_point_field_wrappers = watcher.FieldWrapperList()

        # Temperature field wrappers; computed in `setup`.
        self.temperature_field_wrappers = watcher.FieldWrapperList()

        # Compute dict of (sal_name, sal_index): list of topic attribute names,
        # in order to creat remote_info_list
        topic_names_dict = dict()
        for sensor_info in itertools.chain(
            config.dew_point_sensors, config.temperature_sensors
        ):
            name, index = salobj.name_to_name_index(sensor_info["sal_name"])
            topic_attr_names = [
                "tel_" + topic["topic_name"] for topic in sensor_info["topics"]
            ]
            if (name, index) not in topic_names_dict:
                topic_names_dict[(name, index)] = topic_attr_names
            else:
                topic_names_dict[(name, index)] += topic_attr_names

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
$schema: 'http://json-schema.org/draft-07/schema#'
$id: 'https://github.com/lsst-ts/ts_watcher/Enabled.yaml'
description: Configuration for Enabled
type: object
properties:
  name:
    description: 'Telescope being monitored, typically AuxTel or MainTel'
    type: string
  dew_point_sensors:
    description: Dew point and humidity sensors to monitor.
    type: array
    minItems: 1
    items:
      type: object
      properties:
        sal_name:
          description: 'SAL component name[:SAL index] e.g. ESS:1'
          type: string
        topics:
          type: array
          minItems: 1
          items:
            type: object
            properties:
              topic_name:
                description: name of ESS telemetry topic
                type: string
              sensor_type:
                description: >-
                  Options are: - dewpoint: sensor provides dewPoint directly -
                  humidity: sensor provides relativeHumidity and temperature;
                    the rule computes dewpoint
                type: string
                enum:
                  - humidity
                  - dewpoint
              sensor_names:
                description: Values of sensorName field to read.
                type: array
                minItems: 1
                items:
                  type: string
            required:
              - topic_name
              - sensor_type
              - sensor_names
            additionalProperties: false
      required:
        - sal_name
        - topics
      additionalProperties: false
    required:
      - index
      - topics
    additionalProperties: false
  temperature_sensors:
    description: Temperature sensors to monitor.
    type: array
    minItems: 1
    items:
      type: object
      properties:
        sal_name:
          description: 'SAL component name[:SAL index] e.g. ESS:1'
          type: string
        topics:
          type: array
          minItems: 1
          items:
            type: object
            properties:
              topic_name:
                description: name of ESS telemetry topic
                type: string
              sensor_field_names:
                description: 'list of [sensorName, fieldName, indices]'
                type: array
                minItems: 1
                items:
                  type: object
                  properties:
                    sensor_name:
                      description: value of sensorName field
                      type: string
                    field_name:
                      description: 'field name containing the data, typically temperature'
                      type: string
                    indices:
                      description: >-
                        indices of the data to read (optional). If omitted then
                        read all non-nan values. Must be omitted if the field is
                        a scalar.
                      type: array
                      items:
                        type: integer
                  required:
                    - sensor_name
                    - field_name
                  additionalProperties: false
            required:
              - topic_name
              - sensor_field_names
            additionalProperties: false
      required:
        - sal_name
        - topics
      additionalProperties: false
  warning_level:
    description: The temperature - dewPoint (C) above which a warning alarm is issued.
    type: number
    default: 3
  serious_level:
    description: The temperature - dewPoint (C) above which a serious alarm is issued.
    type: number
    default: 2
  hysteresis:
    description: The temperature drop (C) below which an alarm level is deactivated
    type: number
    default: 0.2
  poll_interval:
    description: Time delay between polling updates (second)
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
  - warning_level
  - serious_level
  - hysteresis
  - poll_interval
  - max_data_age
additionalProperties: false
       """
        return yaml.safe_load(schema_yaml)

    def setup(self, model):
        """Create filtered topic wrappers."""
        dewpoint_wrapper_factory_dict = dict(
            dewpoint=functools.partial(
                watcher.FilteredFieldWrapper, field_name="dewPoint"
            ),
            humidity=DewPointFromHumidityWrapper,
        )
        for dew_point_sensor_info in self.config.dew_point_sensors:
            name, index = salobj.name_to_name_index(dew_point_sensor_info["sal_name"])
            remote = model.remotes[(name, index)]
            for topic_info in dew_point_sensor_info["topics"]:
                topic_attr_name = "tel_" + topic_info["topic_name"]
                topic = getattr(remote, topic_attr_name)

                wrapper_factory = dewpoint_wrapper_factory_dict[
                    topic_info["sensor_type"]
                ]
                for sensor_name in topic_info["sensor_names"]:
                    field_wrapper = wrapper_factory(
                        model=model,
                        topic=topic,
                        filter_field=ESSFilterField,
                        filter_value=sensor_name,
                    )
                    self.dew_point_field_wrappers.add_wrapper(field_wrapper)

        for temperature_sensor_info in self.config.temperature_sensors:
            name, index = salobj.name_to_name_index(temperature_sensor_info["sal_name"])
            remote = model.remotes[(name, index)]
            for topic_info in temperature_sensor_info["topics"]:
                topic_attr_name = "tel_" + topic_info["topic_name"]
                topic = getattr(remote, topic_attr_name)

                for sensor_field_name in topic_info["sensor_field_names"]:
                    sensor_name = sensor_field_name["sensor_name"]
                    field_name = sensor_field_name["field_name"]
                    indices = sensor_field_name.get("indices", None)
                    if indices is not None:
                        field_wrapper = watcher.IndexedFilteredFieldWrapper(
                            model=model,
                            topic=topic,
                            filter_field=ESSFilterField,
                            filter_value=sensor_name,
                            field_name=field_name,
                            indices=indices,
                        )
                    else:
                        field_wrapper = watcher.FilteredFieldWrapper(
                            model=model,
                            topic=topic,
                            filter_field=ESSFilterField,
                            filter_value=sensor_name,
                            field_name=field_name,
                        )
                    self.temperature_field_wrappers.add_wrapper(field_wrapper)

    def start(self):
        self.poll_loop_task.cancel()
        self.poll_loop_task = asyncio.create_task(self.poll_loop())

    def stop(self):
        self.poll_loop_task.cancel()

    async def poll_loop(self):
        self.last_data_tai = utils.current_tai()
        while True:
            severity, reason = self()
            self.alarm.set_severity(severity=severity, reason=reason)
            await asyncio.sleep(self.config.poll_interval)

    def __call__(self, topic_callback=None):
        # List of (dew_point, wrapper, index)
        current_tai = utils.current_tai()
        dew_points = self.dew_point_field_wrappers.get_data(
            max_age=self.config.max_data_age
        )
        # List of (temperature, wrapper, index)
        temperatures = self.temperature_field_wrappers.get_data(
            max_age=self.config.max_data_age
        )
        if not dew_points or not temperatures:
            nodata_age = current_tai - self.last_data_tai
            if nodata_age > self.config.max_data_age:
                missing_strs = []
                if not dew_points:
                    missing_strs.append("dew point")
                if not temperatures:
                    missing_strs.append("temperature")
                missing_data = " or ".join(missing_strs)
                return (
                    AlarmSeverity.SERIOUS,
                    f"No {missing_data} data seen for {nodata_age:0.2} seconds",
                )
            else:
                return watcher.NoneNoReason
        self.last_data_tai = current_tai

        max_dew_point, dew_point_wrapper, dew_point_index = max(
            dew_points, key=lambda v: v[0]
        )
        min_temperature, temperature_wrapper, temperature_index = min(
            temperatures, key=lambda v: v[0]
        )
        dew_point_depression = min_temperature - max_dew_point

        make_severity_reason = functools.partial(
            self._make_severity_reason,
            dew_point_depression=dew_point_depression,
            dew_point_wrapper=dew_point_wrapper,
            dew_point_index=dew_point_index,
            temperature_wrapper=temperature_wrapper,
            temperature_index=temperature_index,
        )

        if dew_point_depression < self.config.serious_level:
            return make_severity_reason(
                severity=AlarmSeverity.SERIOUS, with_hysteresis=False
            )
        elif (
            self.alarm.severity == AlarmSeverity.SERIOUS
            and dew_point_depression
            < self.config.serious_level + self.config.hysteresis
        ):
            return make_severity_reason(
                severity=AlarmSeverity.SERIOUS, with_hysteresis=True
            )
        elif dew_point_depression < self.config.warning_level:
            return make_severity_reason(
                severity=AlarmSeverity.WARNING, with_hysteresis=False
            )
        elif (
            self.alarm.severity == AlarmSeverity.WARNING
            and dew_point_depression
            < self.config.warning_level + self.config.hysteresis
        ):
            return make_severity_reason(
                severity=AlarmSeverity.WARNING, with_hysteresis=True
            )
        return watcher.NoneNoReason

    def _make_severity_reason(
        self,
        severity,
        with_hysteresis,
        dew_point_depression,
        dew_point_wrapper,
        dew_point_index,
        temperature_wrapper,
        temperature_index,
    ):
        """Make (alarm severity, reason).

        Parameters
        ----------
        severity : `AlarmSeverity`
            Alarm severity; must be WARNING or SERIOUS.
        with_hysteresis : `bool`
            Should the reason include hysteresis?
        dew_point_depression : `float`
            Dew point depression (C).
        dew_point_wrapper : `BaseFilteredTopicWrapper`
            Field wrapper for the dew point value used.
        dew_point_index : `int` or `None`
            Index of the dew point value used.
        temperature_wrapper : `BaseFilteredTopicWrapper`
            Field wrapper for the dew point value used.
        temperature_index : `int` or `None`
            Index of the dew point value used.
        """
        if severity is AlarmSeverity.WARNING:
            threshold = self.config.warning_level
        elif severity is AlarmSeverity.SERIOUS:
            threshold = self.config.serious_level
        else:
            raise ValueError(f"Unsupported severity {severity!r}")

        if with_hysteresis:
            value_str = (
                f"Dew point depression {dew_point_depression:0.2f} "
                f"- hysteresis {self.config.hysteresis:0.2f}"
            )
        else:
            value_str = f"Dew point depression {dew_point_depression:0.2f}"

        dew_point_descr = self.dew_point_field_wrappers.get_descr(
            dew_point_wrapper, dew_point_index
        )
        temperature_descr = self.temperature_field_wrappers.get_descr(
            temperature_wrapper, temperature_index
        )
        reason = (
            f"{value_str} < {threshold:0.2f} as reported by "
            f"dew point {dew_point_descr} and temperature {temperature_descr}"
        )

        return (severity, reason)
