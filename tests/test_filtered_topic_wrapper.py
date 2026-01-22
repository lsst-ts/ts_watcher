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

import asyncio
import unittest

import pytest

from lsst.ts import salobj, utils, watcher

index_gen = utils.index_generator()

# Timeout for basic operations (seconds)
STD_TIMEOUT = 5


class FilteredTopicWrapperTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()
        self.index = next(index_gen)

    async def test_basics(self):
        model = watcher.MockModel(enabled=True)
        filter_field = "int0"
        data_field = "double0"

        async with (
            salobj.Controller(name="Test", index=self.index) as controller,
            salobj.Remote(
                domain=controller.domain,
                name="Test",
                index=self.index,
                readonly=True,
                include=["scalars"],
            ) as remote,
        ):
            topic = remote.tel_scalars
            wrapper = model.make_filtered_topic_wrapper(topic=topic, filter_field=filter_field)

            # Test wrapper attributes
            assert wrapper.filter_field == filter_field
            assert wrapper.topic is topic
            assert isinstance(wrapper.descr, str)
            assert topic.salinfo.name_index in wrapper.descr
            assert topic.attr_name in wrapper.descr
            assert wrapper.data_cache == dict()
            assert vars(wrapper.default_data) == vars(topic.DataType())

            # Test that a TopicCallback was created and the wrapper added.
            assert isinstance(topic.callback, watcher.TopicCallback)
            assert topic.callback.topic_wrappers == [wrapper]

            # Test that the wrapper was added to the filtered topic wrapper
            # registry
            assert model.get_filtered_topic_wrapper(topic=topic, filter_field=filter_field) is wrapper

            # Test topic callback handling
            data_dict_list = [
                {filter_field: 1, data_field: 3.5},
                {filter_field: 2, data_field: 2.4},
                {filter_field: 1, data_field: -13.1},
                {filter_field: 2, data_field: -13.1},
            ]
            expected_doubles = dict()
            for i, data_dict in enumerate(data_dict_list):
                filter_value = data_dict[filter_field]
                expected_doubles[filter_value] = data_dict[data_field]
                wrapper.call_event.clear()
                await controller.tel_scalars.set_write(**data_dict)
                await asyncio.wait_for(wrapper.call_event.wait(), timeout=STD_TIMEOUT)
                wrapper_data = wrapper.get_data(filter_value)
                assert wrapper_data is not None
                assert wrapper_data.double0 == data_dict[data_field]
                assert wrapper_data is wrapper.data_cache[filter_value]

            assert wrapper.data_cache.keys() == expected_doubles.keys()
            for key, value in wrapper.data_cache.items():
                assert value.double0 == expected_doubles[key]

            # Test that make_filtered_topic_wrapper returns an existing
            # wrapper, if possible.
            wrapper2 = model.make_filtered_topic_wrapper(topic=topic, filter_field=filter_field)
            assert wrapper is wrapper2

            # Test get_filtered_topic_wrapper with a non-existent wrapper
            with pytest.raises(KeyError):
                model.get_filtered_topic_wrapper(topic=topic, filter_field="short0")

    async def test_constructor_errors(self):
        model = watcher.MockModel(enabled=True)
        filter_field = "int0"

        async with (
            salobj.Controller(name="Test", index=self.index) as controller,
            salobj.Remote(
                domain=controller.domain,
                name="Test",
                index=self.index,
                readonly=True,
                include=["arrays", "scalars"],
            ) as remote,
        ):
            # Test a good wrapper
            wrapper = model.make_filtered_topic_wrapper(topic=remote.evt_scalars, filter_field=filter_field)
            assert isinstance(wrapper, watcher.FilteredTopicWrapper)
            assert wrapper.filter_field == filter_field

            # Test a nonexistent filter_field
            with pytest.raises(ValueError):
                model.make_filtered_topic_wrapper(topic=remote.evt_scalars, filter_field="no_such_field")

            # Test an array filter_field
            with pytest.raises(ValueError):
                model.make_filtered_topic_wrapper(topic=remote.evt_arrays, filter_field=filter_field)
