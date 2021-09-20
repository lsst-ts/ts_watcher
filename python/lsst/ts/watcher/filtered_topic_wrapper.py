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
    "get_filtered_topic_wrapper_key",
    "FilteredTopicWrapper",
]

import collections

from .topic_callback import get_topic_key, TopicCallback


def get_filtered_topic_wrapper_key(topic_key, filter_field):
    """Get a key for a filtered topic wrapper."""
    return topic_key + (filter_field,)


class FilteredTopicWrapper:
    r"""Topic wrapper that caches data by the value of a filter field.

    To make a topic wrapper call `Model.make_filtered_topic_wrapper`,
    instead of constructing a `TopicWrapper` directly. That allows using
    a cached instance, if available (and avoids a `RuntimeError`
    in the constructor, if an instance exists).

    Parameters
    ----------
    model : `Model`
        Watcher model. Used to add a TopicCallback to the topic,
        if one does not already exist.
    topic : `lsst.ts.salobj.ReadTopic`
        Topic to read.
    filter_field : `str`
        Field to filter on. The field must be a scalar.
        It should also have a smallish number of expected values,
        in order to avoid caching too much data.

    Raises
    ------
    ValueError
        If filter_field does not exist in the data,
        or if it exists but is an array.
    RuntimeError
        If this FilteredFieldWrapper already exists in the model.
        To avoid this, construct field wrappers by calling
        `Model.make_filtered_field_wrapper`.

    Attributes
    ----------
    topic : `lsst.ts.salobj.ReadTopic`
        ``topic`` constructor argument.
    filter_field : `str`
        ``filter_field`` constructor argument.
    descr : `str`
        A short description of the wrapper.
    data_cache : `str`
        Dict of value of filter_field: most recent data seen for that value.
    default_data
        Default-constructed data. Use for validation of field wrappers.

    Notes
    -----
    A rule will typically use filtered _field_ wrappers (subclasses
    of `BaseFilteredFieldWrapper`) rather than `FilteredTopicWrapper`.

    Filtered field wrappers are high-level objects that store data for
    a particular value of filter_field (e.g. a particular subsystem).
    `FilteredTopicWrapper` is lower level object that stores data for
    all values of ``filter_field`` (e.g. all subsystems).

    Each `BaseFilteredFieldWrapper` contains a `FilteredTopicWrapper`.
    """

    def __init__(self, model, topic, filter_field):
        key = get_filtered_topic_wrapper_key(
            topic_key=get_topic_key(topic), filter_field=filter_field
        )
        if key in model.filtered_topic_wrappers:
            raise RuntimeError(
                "This FilteredTopicWrapper already exists in the model; "
                "please use model.make_topic_filter_wrapper, instead of"
                "constructing FilteredTopicWrapper directly."
            )
        if topic.callback is None:
            topic.callback = TopicCallback(topic=topic, rule=None, model=model)
        self.default_data = topic.DataType()
        default_filter_value = getattr(self.default_data, filter_field, None)
        if default_filter_value is None:
            raise ValueError(f"topic {topic} has no field named {filter_field}")
        elif isinstance(default_filter_value, list):
            raise ValueError(
                f"topic {topic} filter field {filter_field} must be a scalar"
            )

        self.topic = topic
        self.filter_field = filter_field
        self.descr = f"{topic.salinfo.name_index}.{topic.attr_name}"

        # Data cache: a dict of filter_value: data
        self.data_cache = dict()

        # dict of filter_value: list of field wrappers
        self.field_wrappers = collections.defaultdict(list)

        self.topic.callback.add_topic_wrapper(self)

        model.filtered_topic_wrappers[key] = self

    def add_field_wrapper(self, field_wrapper):
        """Add a field wrapper to the internal cache.

        Call field_wrapper.update_value when update_data is called
        with the appropriate filter_value.
        """
        self.field_wrappers[field_wrapper.filter_value].append(field_wrapper)

    def get_data(self, filter_value):
        """Get the most recently seen data for the given filter_value,
        or None if no data seen.
        """
        return self.data_cache.get(filter_value, None)

    def __call__(self, topic_callback):
        """Update the cached data."""
        data = topic_callback.get()
        timestamp = data.private_sndStamp
        filter_value = getattr(data, self.filter_field)
        self.data_cache[filter_value] = data
        for field_wrapper in self.field_wrappers.get(filter_value, []):
            field_wrapper.update_value(data)
            field_wrapper.timestamp = timestamp

    def __str__(self):
        return self.descr
