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

__all__ = [
    "BaseFilteredFieldWrapper",
    "FilteredEssFieldWrapper",
    "IndexedFilteredEssFieldWrapper",
]

import abc


class BaseFilteredFieldWrapper(abc.ABC):
    """Base class for filtered field wrappers.

    Extract and cache the most recent value of a topic field
    for data that matches a specified filter.

    See also `FieldWrapperList` to hold a collection of related
    filtered field wrappers.

    Parameters
    ----------
    model : `Model`
        Watcher model.
    topic : `lsst.ts.salobj.ReadTopic`
        Topic to read.
    filter_field : `str`
        Name of filter field.
    filter_value : `str`
        Required value of the filter field.

    Raises
    ------
    ValueError
        If field wrapper validation fails.

    Attributes
    ----------
    topic_wrapper : `TopicWrapper`
        Topic wrapper for the specified topic.
    filter_value : `str`
        Value of ``filter_value`` constructor argument.
    topic_descr : `str`
        A brief description of this topic, including SAL name and index,
        topic attribute name, filter_field, and filter_value.
        Does not include any information about the field;
        subclasses are responsible for handling that in `get_value_descr`.
    nelts : `int`
        The number of elements in ``value``, if it is a list, else None.
        This is based on the topic schema; it has nothing to do with
        whether or not any data has been seen for the topic.
    value
        The most recently seen value for this field,
        or None if data has never been seen.
    timestamp : `float`
        The time the data was last set (TAI unix seconds);
        None until set.
    """

    def __init__(self, model, topic, filter_field, filter_value):
        self.topic_wrapper = model.make_filtered_topic_wrapper(
            topic=topic, filter_field=filter_field
        )
        self.filter_value = filter_value
        self.topic_descr = f"{self.topic_wrapper.descr}({filter_field}={filter_value})"
        self.nelts = self._get_nelts(self.topic_wrapper.default_data)
        self.value = None
        self.timestamp = None
        self.topic_wrapper.add_field_wrapper(self)

    @abc.abstractmethod
    def update_value(self, data):
        """Set ``value`` from DDS data.

        Do not set the ``timestamp`` field, and do not check that
        ``getattr(data, filter_field) == self.filter_value``; both of these
        are done by the caller: `FilteredTopicWrapper.__call__`.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def _get_nelts(self, data):
        """Check the configuration with default data and return the
        number of elements (None if a scalar).

        Parameters
        ----------
        data : DDS data
            DDS data sample (default-constructed).

        Raises
        ------
        ValueError
            If validation fails.

        Notes
        -----
        The contained topic wrapper checks for the existence of
        the filter field, so this method does not have to bother.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def get_value_descr(self, index):
        """Get a description for a value.

        The description should include a high-level description, if available,
        plus details of which field provided the data (if not synthesized),
        and self.topic_descr.

        Parameters
        ----------
        index : `int` or `None`
            The index of the value; must be `None` for a scalar.

        Raises
        ------
        RuntimeError
            If the field is indexed and the index is None or out of range.
            If the field is not indexed and the index is not None.
        """
        raise NotImplementedError()

    def __str__(self):
        return self.topic_descr


class FilteredEssFieldWrapper(BaseFilteredFieldWrapper):
    """Track a field of an ESS telemetry topic, with a particular sensor name.

    Parameters
    ----------
    model : `Model`
        Watcher model.
    topic : `lsst.ts.salobj.ReadTopic`
        Topic to read.
    sensor_name : `str`
        Sensor name to filter on.
        This becomes filter_value in the base class,
        and filter_field is hard-coded to be "sensorName".
    field_name : `str`
        Name of field to read. The field may be a scalar or an array.
    """

    def __init__(
        self,
        model,
        topic,
        sensor_name,
        field_name,
    ):
        self.field_name = field_name
        self.location_scalar = ""
        self.location_arr = [""]
        super().__init__(
            model=model,
            topic=topic,
            filter_field="sensorName",
            filter_value=sensor_name,
        )

    def update_value(self, data):
        self.value = getattr(data, self.field_name)
        if self.nelts is None:
            self.location_scalar = data.location
        else:
            self.location_arr = [value.strip() for value in data.location.split(",")]

    def _get_nelts(self, data):
        value = getattr(data, self.field_name, None)
        if value is None:
            raise ValueError(f"{self} has no field {self.field_name}")
        return len(value) if isinstance(value, list) else None

    def get_value_descr(self, index):
        """Get a description for a value.

        Parameters
        ----------
        index : `int` or `None`
            The index of the value; must be `None` for a scalar,
            and an int for an array.

        Raises
        ------
        ValueError
            If the field is indexed and the index is None or out of range.
            If the field is not indexed and the index is not None.
        """
        if self.nelts is None:
            if index is not None:
                raise ValueError(
                    f"Index={index} must be None for scalar field {self.topic_descr}"
                )
            if self.location_scalar:
                value_descr = f"{self.location_scalar} from {self.topic_descr}"
            else:
                value_descr = self.topic_descr
        else:
            if index is None:
                raise ValueError(
                    f"Index must not be None for array field {self.topic_descr}"
                )
            if index < 0 or index >= self.nelts:
                raise ValueError(
                    f"Index {index} out of range [0, {self.nelts}) for {self.topic_descr}"
                )
            if index < len(self.location_arr):
                value_descr = f"{self.location_arr[index]} from {self.topic_descr}"
            else:
                value_descr = f"{self.topic_descr}[{index}]"

        return value_descr


class IndexedFilteredEssFieldWrapper(FilteredEssFieldWrapper):
    """A filtered field wrapper for an array field, with metadata
    indicating indices of interest.

    `FieldWrapperList` provides a useful way to extract the elements
    of interest.

    Parameters
    ----------
    model : `Model`
        Watcher model.
    topic : `lsst.ts.salobj.ReadTopic`
        Topic to read.
    sensor_name : `str`
        Required value of the ``sensorName`` field.
    field_name : `str`
        Name of field to read. The field must be an array.
    scalar_descr : `str`
        Brief description of the field.
    indices : `list` [`int`]
        Indices of interest. Negative indices are not supported,
        so each index must be in range 0 <= index < self.nelts.
        This is metadata, for use by FieldWrapperList;
        the ``value`` attribute contains all elements,
        just like `FilteredEssFieldWrapper`.

    Notes
    -----
    If you specify indices that are not actually connected to sensors
    then the value will always be nan and so never used.
    There is no warning because the number of connected sensors is not known
    when the wrapper is constructed.
    """

    def __init__(
        self,
        model,
        topic,
        sensor_name,
        field_name,
        indices,
    ):
        if not indices:
            raise ValueError(f"indices={indices} must be a non-empty sequence")
        if not all(isinstance(index, int) for index in indices):
            raise ValueError(f"Each value in indices={indices} must be an integer")
        self.indices = tuple(indices)
        super().__init__(
            model=model,
            topic=topic,
            sensor_name=sensor_name,
            field_name=field_name,
        )

    def _get_nelts(self, data):
        nelts = super()._get_nelts(data)
        if nelts is None:
            raise ValueError(f"field_name={self.field_name} is a scalar")
        bad_indices = [index for index in self.indices if index < 0 or index >= nelts]
        if bad_indices:
            raise ValueError(
                f"One or more indices={bad_indices} out of range; "
                f"field_name={self.field_name} is an array of len={nelts}"
            )
        return nelts
