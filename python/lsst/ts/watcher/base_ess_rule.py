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

__all__ = ["BaseEssRule"]

from lsst.ts import utils
from lsst.ts.idl.enums.Watcher import AlarmSeverity

from .base_rule import AlarmSeverityReasonType, NoneNoReason
from .field_wrapper_list import FieldWrapperList
from .filtered_field_wrapper import (
    FilteredEssFieldWrapper,
    IndexedFilteredEssFieldWrapper,
)
from .polling_rule import PollingRule
from .remote_info import RemoteInfo
from .threshold_handler import ThresholdHandler


class BaseEssRule(PollingRule):
    """Check one kind of ESS data, e.g. temperature or humidity.

    Parameters
    ----------
    config : struct
        Rule configuration. The following fields are read:

        * warning_level : `float` | `None`
          Warning level. None to not use this level.
        * serious_level : `float` | `None`
          Serious level. None to not use this level.
        * critical_level : `float` | `None`
          Critical level. None to not use this level.
        * hysteresis : `float`
          The amount by which the measurement must decrease below
          (or increase above if ``big_is_bad`` false) a severity level,
          before alarm severity is decreased.
        * {sensor_info_name}
          A field whose name is given by ``sensor_info_name``
          that contains information about the sensors to read.
          A list of dicts whose format depends on is_indexed.
          If is_indexed false, the fields are:

          * sal_index : int
            SAL index of topic.
          * sensor_names : list[str]
            A list of sensor names.

          If is_indexed true, the fields are:

          * sal_index : int
            SAL index of topic.
          * sensor_info : list[dict[str, str | list[int]]]
            A list of topic-specific sensor info with fields:

            * sensor_name : str
              Name of sensor.
            * indices : list[int], optional
              Indices of field to read.
              If omitted then read all non-nan values.
        * warning_msg : `str`, optional
          The first part of the reason string for a warning alarm.
          This should say what the operators should do.
        * serious_msg : `str`, optional
          The first part of the reason string for a serious alarm.
          This should say what the operators should do.
        * critical_msg : `str`, optional
          The first part of the reason string for a critical alarm.
          This should say what the operators should do.


    name : `str`
        The name of the rule.
    topic_attr_name : `str`
        The attr name of the ESS telemetry topic, e.g. "tel_temperature"
        or "tel_relativeHumidity".
    field_name : `str`
        The name of the ESS topic field, e.g. "temperature" or "humidity".
    sensor_info_name : `str`
        Name of sensor info field in ``config``.
    is_indexed : `bool`
        Is the field indexed? This controls the format of sensor info
        in the config.
    units : `str`
        Units of measurement.
    value_format : `str`, optional
        Format for float value (threshold level or measured value)
        without a leading colon, e.g. "0.2f"


    Attributes
    ----------
    PollingRule attributes
        All attributes from `PollingRule`, plus:
    field_wrappers : `FieldWrapperList`
        Wrappers for ESS telemetry fields.
    sensors : `dict`
        Sensor configuration (the config field specified by
        ``sensor_field_info_name``).
    threshold_handler : `ThresholdHandler`
        Threshold handler for ESS data.

    Notes
    -----
    This uses `FilteredEssFieldWrapper` and its kin, because ESS data must be
    filtered by the value of the ``sensorName`` field (and index, if the data
    is array-valued).
    """

    def __init__(
        self,
        *,
        config,
        name,
        topic_attr_name,
        field_name,
        sensor_info_name,
        big_is_bad,
        is_indexed,
        units,
        value_format="0.2f",
    ):
        self.topic_attr_name = topic_attr_name
        self.field_name = field_name
        self.is_indexed = is_indexed
        self.sensors = getattr(config, sensor_info_name)

        # Field wrappers; computed in `setup`.
        self.field_wrappers = FieldWrapperList()

        self.threshold_handler = ThresholdHandler(
            warning_level=getattr(config, "warning_level", None),
            serious_level=getattr(config, "serious_level", None),
            critical_level=getattr(config, "critical_level", None),
            warning_msg=getattr(config, "warning_msg", None),
            serious_msg=getattr(config, "serious_msg", None),
            critical_msg=getattr(config, "critical_msg", None),
            hysteresis=config.hysteresis,
            big_is_bad=big_is_bad,
            value_name=field_name,
            units=units,
            value_format=value_format,
        )

        # Compute dict of (sal_name, sal_index): list of topic attribute names,
        # in order to create remote_info_list
        topic_names_dict = dict()
        sal_name = "ESS"
        topic_attr_names = [topic_attr_name]
        for sensor_info in self.sensors:
            sal_index = sensor_info["sal_index"]
            sal_name_index = (sal_name, sal_index)
            if sal_name_index not in topic_names_dict:
                topic_names_dict[sal_name_index] = topic_attr_names
            else:
                topic_names_dict[sal_name_index] += topic_attr_names

        remote_info_list = [
            RemoteInfo(
                name=name,
                index=sal_index,
                callback_names=None,
                poll_names=topic_attr_names,
            )
            for (name, sal_index), topic_attr_names in topic_names_dict.items()
        ]

        super().__init__(
            config=config,
            name=name,
            remote_info_list=remote_info_list,
        )

    def setup(self, model):
        """Create filtered topic wrappers

        Parameters
        ----------
        model : `Model`
            The watcher model.
        """
        sal_name = "ESS"
        for sensor_info in self.sensors:
            sal_index = sensor_info["sal_index"]
            remote = model.remotes[(sal_name, sal_index)]
            topic = getattr(remote, self.topic_attr_name)
            if self.is_indexed:
                for topic_specific_sensor_info in sensor_info["sensor_info"]:
                    sensor_name = topic_specific_sensor_info["sensor_name"]
                    indices = topic_specific_sensor_info.get("indices", None)
                    if indices is not None:
                        field_wrapper = IndexedFilteredEssFieldWrapper(
                            model=model,
                            topic=topic,
                            sensor_name=sensor_name,
                            field_name=self.field_name,
                            indices=indices,
                        )
                    else:
                        field_wrapper = FilteredEssFieldWrapper(
                            model=model,
                            topic=topic,
                            sensor_name=sensor_name,
                            field_name=self.field_name,
                        )
                    self.field_wrappers.add_wrapper(field_wrapper)
            else:
                for sensor_name in sensor_info["sensor_names"]:
                    field_wrapper = FilteredEssFieldWrapper(
                        model=model,
                        topic=topic,
                        sensor_name=sensor_name,
                        field_name=self.field_name,
                    )
                    self.field_wrappers.add_wrapper(field_wrapper)

    def compute_alarm_severity(self) -> AlarmSeverityReasonType:
        current_tai = utils.current_tai()
        # List of (reported_value, field_wrapper, index)
        reported_values = self.field_wrappers.get_data(max_age=self.config.max_data_age)
        if not reported_values:
            poll_duration = current_tai - self.poll_start_tai
            severity_reason = (
                (
                    AlarmSeverity.SERIOUS,
                    f"No {self.topic_attr_name} data seen for {self.config.max_data_age} seconds",
                )
                if poll_duration > self.config.max_data_age
                else NoneNoReason
            )
            return severity_reason

        # We got data; use the most pessimistic measured value.
        reported_value, field_wrapper, wrapper_index = max(
            reported_values, key=lambda v: v[0]
        )
        source_descr = field_wrapper.get_value_descr(wrapper_index)
        return self.threshold_handler.get_severity_reason(
            value=reported_value,
            current_severity=self.alarm.severity,
            source_descr=source_descr,
        )
