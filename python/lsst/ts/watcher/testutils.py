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

__all__ = ["MockModel"]

from .filtered_topic_wrapper import get_filtered_topic_wrapper_key, FilteredTopicWrapper
from .topic_callback import get_topic_key


class MockModel:
    def __init__(self, enabled=False):
        self.enabled = enabled
        self.filtered_topic_wrappers = dict()

    def get_filtered_topic_wrapper(self, topic, filter_field):
        """Get an existing `TopicWrapper`.

        Parameters
        ----------
        topic : `lsst.ts.salobj.ReadTopic`
            Topic to read.
        filter_field : `str`
            Field to filter on. The field must be a scalar.
            It should also have a smallish number of expected values,
            in order to avoid caching too much data.

        Raises
        ------
        KeyError
            If the wrapper is not in the registry.
        """
        key = get_filtered_topic_wrapper_key(
            topic_key=get_topic_key(topic), filter_field=filter_field
        )
        return self.filtered_topic_wrappers[key]

    def make_filtered_topic_wrapper(self, topic, filter_field):
        """Make a TopicWrapper, or return an existing one, if found.

        Call this instead of constructing `TopicWrapper` directly.

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
        """
        key = get_filtered_topic_wrapper_key(
            topic_key=get_topic_key(topic), filter_field=filter_field
        )
        wrapper = self.filtered_topic_wrappers.get(key, None)
        if wrapper is None:
            wrapper = FilteredTopicWrapper(
                model=self, topic=topic, filter_field=filter_field
            )
            self.filtered_topic_wrappers[key] = wrapper
        return wrapper
