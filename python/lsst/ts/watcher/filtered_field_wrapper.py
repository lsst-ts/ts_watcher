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
    "FilteredFieldWrapper",
    "IndexedFilteredFieldWrapper",
]

import abc

import numpy as np


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
    field_descr : `str`
        Brief description of the field.

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
    descr : `str`
        A brief description of this topic filter wrapper.
    nelts : `int`
        The number of elements in ``value``, if it is a list, else None.
        This is based on the topic schema; it has nothing to do with
        whether or not any data has been seen for the topic.
    value
        The most recently seen value for this field,
        or None if data has never been seen.
    timestamp
        The time the data was last set (TAI unix seconds);
        None until set.
    """

    def __init__(self, model, topic, filter_field, filter_value, field_descr):
        self.topic_wrapper = model.make_filtered_topic_wrapper(
            topic=topic, filter_field=filter_field
        )
        self.filter_value = filter_value
        field_descr_list = []
        if field_descr is not None:
            field_descr_list.append(field_descr)
        if filter_value is not None:
            field_descr_list.append(f"filter_value={self.filter_value}")
        field_str = ", ".join(field_descr_list)
        self.descr = f"{self.topic_wrapper.descr}({field_str})"

        self.nelts = self._get_nelts(self.topic_wrapper.default_data)

        self.value = None
        self.timestamp = None
        self.topic_wrapper.add_field_wrapper(self)

    @abc.abstractmethod
    def update_value(self, data):
        """Set ``value`` from data.

        Do not set the ``timestamp`` field, and do not check that
        ``getattr(data, filter_field) == self.filter_value``; both of these
        are done by the caller: `FilteredTopicWrapper.__call__`.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def _get_nelts(self, data):
        """Check the configuration with default data and return the
        number of elements (None if a scalar).

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

    def __str__(self):
        return self.descr


class FilteredFieldWrapper(BaseFilteredFieldWrapper):
    """Track a specified field.

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
    field_name : `str`
        Name of field to read. The field must be a scalar.
    """

    def __init__(self, model, topic, filter_field, filter_value, field_name):
        self.field_name = field_name
        super().__init__(
            model=model,
            topic=topic,
            filter_field=filter_field,
            filter_value=filter_value,
            field_descr=field_name,
        )

    def update_value(self, data):
        """Set value from non-None data."""
        self.value = getattr(data, self.field_name)

    def _get_nelts(self, data):
        value = getattr(data, self.field_name, None)
        if value is None:
            raise ValueError(f"{self} has no field {self.field_name}")
        return len(value) if isinstance(value, list) else None


class IndexedFilteredFieldWrapper(FilteredFieldWrapper):
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
    filter_field : `str`
        Name of filter field.
    filter_value : `str`
        Required value of the filter field.
    field_name : `str`
        Name of field to read. The field must be an array.
    indices : `tuple` [`int`]
        Indices of interest. Negative indices are relative to the end.
        This is purely metadata; the ``value`` attribute contains all elements,
        just like `FilteredFieldWrapper`.
    """

    def __init__(self, model, topic, filter_field, filter_value, field_name, indices):
        if not indices:
            raise ValueError(f"indices={indices} must be a non-empty sequence")
        if not all(isinstance(index, int) for index in indices):
            raise ValueError(f"Each value in indices={indices} must be an integer")
        self.indices = tuple(indices)
        super().__init__(
            model=model,
            topic=topic,
            filter_field=filter_field,
            filter_value=filter_value,
            field_name=field_name,
        )

    def _get_nelts(self, data):
        nelts = super()._get_nelts(data)
        if nelts is None:
            raise ValueError(f"field_name={self.field_name} is a scalar")
        values = getattr(data, self.field_name)
        try:
            np.take(values, self.indices)
        except IndexError:
            raise ValueError(
                f"One or more indices={self.indices} out of range; "
                f"field_name={self.field_name} is an array of len={nelts}"
            )
        return nelts
