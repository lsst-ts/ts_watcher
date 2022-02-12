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
import itertools
import pytest
import unittest

import numpy as np
import numpy.random

from lsst.ts import salobj
from lsst.ts import utils
from lsst.ts import watcher

index_gen = utils.index_generator()

# Timeout for basic operations (seconds)
STD_TIMEOUT = 5


class FilteredFieldWrapperTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()
        self.index = next(index_gen)

    async def test_scalar_ess_field(self):
        """Test `FilteredEssFieldWrapper` with a scalar field."""
        model = watcher.MockModel(enabled=True)
        filter_field = "sensorName"
        data_field = "temperature"

        filter_values = ["one", "two"]
        # Dict of sensor_name: FilteredEssFieldWrapper
        field_wrappers = dict()

        async with salobj.Controller(
            name="ESS", index=self.index
        ) as controller, salobj.Remote(
            domain=controller.domain,
            name="ESS",
            index=self.index,
            readonly=True,
            include=["hx85a"],
        ) as remote:
            topic = remote.tel_hx85a

            topic_wrapper = None
            for i, sensor_name in enumerate(filter_values):
                field_wrapper = watcher.FilteredEssFieldWrapper(
                    model=model,
                    topic=topic,
                    sensor_name=sensor_name,
                    field_name=data_field,
                )
                field_wrappers[sensor_name] = field_wrapper

                if i == 0:
                    # The first filtered field wrapper should create
                    # a filtered topic wrapper
                    topic_wrapper = model.get_filtered_topic_wrapper(
                        topic=topic, filter_field=filter_field
                    )

                    # Test that a TopicCallback was created
                    # and the topic wrapper added
                    assert topic.callback is not None
                    assert isinstance(topic.callback, watcher.TopicCallback)
                    assert topic.callback.topic_wrappers == [topic_wrapper]

                # Test field wrapper attributes
                assert field_wrapper.topic_wrapper is topic_wrapper
                assert field_wrapper.filter_value == sensor_name
                assert field_wrapper.nelts is None
                assert str(sensor_name) in field_wrapper.topic_descr
                assert field_wrapper.value is None
                assert field_wrapper.timestamp is None

            rng = numpy.random.default_rng(seed=47)

            def random_float():
                """Return a random float32."""
                return rng.random(1, dtype=np.float32)[0]

            # Write data and see if it is correctly received.
            filter_cycle = itertools.cycle(filter_values)
            location_str_dict = {}
            data_dict_list = []
            for i in range(5):
                sensor_name = next(filter_cycle)
                data_dict_list.append(
                    {
                        filter_field: sensor_name,
                        data_field: random_float(),
                        "location": f"{data_field} at location of {sensor_name}",
                    }
                )
            # Dict of sensor_name: expected field wrapper value
            expected_values = {value: None for value in filter_values}
            for data_dict in data_dict_list:
                sensor_name = data_dict[filter_field]
                location_str_dict[sensor_name] = data_dict["location"]
                expected_values[sensor_name] = data_dict[data_field]
                topic_wrapper.call_event.clear()
                controller.tel_hx85a.set_put(**data_dict)
                await asyncio.wait_for(
                    topic_wrapper.call_event.wait(), timeout=STD_TIMEOUT
                )
                for sensor_name in filter_values:
                    field_wrapper = field_wrappers[sensor_name]
                    if expected_values[sensor_name] is None:
                        assert field_wrapper.value is None
                        assert field_wrapper.timestamp is None
                        expected_location_str = ""
                    else:
                        assert field_wrapper.value == expected_values[sensor_name]
                        expected_timestamp = topic_wrapper.data_cache[
                            sensor_name
                        ].private_sndStamp
                        assert field_wrapper.timestamp == expected_timestamp
                        expected_location_str = location_str_dict[sensor_name]

                    # Test the get_value_descr method.
                    for bad_index in (-1, 0, 1):
                        # Any non-None value should raise,
                        # but only ints make sense.
                        with pytest.raises(ValueError):
                            field_wrapper.get_value_descr(index=bad_index)
                    value_descr = field_wrapper.get_value_descr(index=None)
                    assert field_wrapper.topic_descr in value_descr
                    if expected_location_str:
                        assert expected_location_str in value_descr

    async def test_array_ess_field(self):
        """Test `FilteredEssFieldWrapper` and `IndexedFilteredEssFieldWrapper`
        with an array field.
        """
        model = watcher.MockModel(enabled=True)
        filter_field = "sensorName"
        data_field = "temperature"

        filter_values = ["one", "two"]

        # Dict of sensor_name: FilteredEssFieldWrapper
        field_wrappers = dict()
        # Dict of (sensor_name, indices): IndexedFilteredEssFieldWrapper
        indexed_field_wrappers = dict()

        async with salobj.Controller(
            name="ESS", index=self.index
        ) as controller, salobj.Remote(
            domain=controller.domain,
            name="ESS",
            index=self.index,
            readonly=True,
            include=["temperature"],
        ) as remote:
            topic = remote.tel_temperature
            temperature_len = len(topic.DataType().temperature)

            # Make a location_str with fewer entries than channels, in order to
            # test get_value_descr's handling of missing entries.
            location_arr = [
                f"location for thermometer {i+1}" for i in range(temperature_len // 2)
            ]
            location_str = ", ".join(location_arr)

            # Note: there is no difference between
            # IndexedFilteredEssFieldWrapper instances with different indices
            # beyond the value of the ``indices`` attribute.
            # These choices test whether indices at the extremes are allowed.
            indices_list = [
                (0,),
                (1, temperature_len - 1, 3, 2),
                (1, temperature_len - 2),
            ]

            topic_wrapper = None
            for i, sensor_name in enumerate(filter_values):
                field_wrapper = watcher.FilteredEssFieldWrapper(
                    model=model,
                    topic=topic,
                    sensor_name=sensor_name,
                    field_name=data_field,
                )
                field_wrappers[sensor_name] = field_wrapper

                if i == 0:
                    # The first filtered field wrapper should create
                    # a filtered topic wrapper
                    topic_wrapper = model.get_filtered_topic_wrapper(
                        topic=topic, filter_field=filter_field
                    )

                    # Test that a TopicCallback was created
                    # and the topic wrapper added.
                    assert topic.callback is not None
                    assert isinstance(topic.callback, watcher.TopicCallback)
                    assert topic.callback.topic_wrappers == [topic_wrapper]

                # Test field wrapper attributes
                assert field_wrapper.topic_wrapper is topic_wrapper
                assert field_wrapper.filter_value == sensor_name
                assert field_wrapper.nelts == temperature_len
                assert str(sensor_name) in field_wrapper.topic_descr
                assert field_wrapper.value is None

                for indices in indices_list:
                    indexed_field_wrapper = watcher.IndexedFilteredEssFieldWrapper(
                        model=model,
                        topic=topic,
                        sensor_name=sensor_name,
                        field_name=data_field,
                        indices=indices,
                    )
                    indexed_field_wrappers[
                        (sensor_name, indices)
                    ] = indexed_field_wrapper

                    # Test indexed field wrapper attributes
                    assert indexed_field_wrapper.topic_wrapper is topic_wrapper
                    assert indexed_field_wrapper.filter_value == sensor_name
                    assert indexed_field_wrapper.nelts == temperature_len
                    assert indexed_field_wrapper.indices == indices
                    assert str(sensor_name) in indexed_field_wrapper.topic_descr
                    assert indexed_field_wrapper.value is None

            # Test field callback handling
            rng = numpy.random.default_rng(seed=29)

            def random_floats():
                """Return a list of temerature_len random float32."""
                return list(rng.random(temperature_len, dtype=np.float32))

            # Write data and see if it is correctly received.
            filter_cycle = itertools.cycle(filter_values)
            location_str_dict = {}
            data_dict_list = []
            for i in range(5):
                sensor_name = next(filter_cycle)
                location_arr = [
                    f"location for thermometer {i+1}"
                    for i in range(temperature_len // 2)
                ]
                location_str = ", ".join(location_arr)
                data_dict_list.append(
                    {
                        filter_field: next(filter_cycle),
                        data_field: random_floats(),
                        "location": location_str,
                    }
                )
            # Dict of sensor_name: expected field wrapper value
            expected_values = {value: None for value in filter_values}
            for data_dict in data_dict_list:
                sensor_name = data_dict[filter_field]
                location_str_dict[sensor_name] = data_dict["location"]
                expected_values[sensor_name] = data_dict[data_field]
                topic_wrapper.call_event.clear()
                controller.tel_temperature.set_put(**data_dict)
                await asyncio.wait_for(
                    topic_wrapper.call_event.wait(), timeout=STD_TIMEOUT
                )
                for sensor_name in filter_values:
                    expected_value = expected_values[sensor_name]
                    field_wrapper = field_wrappers[sensor_name]
                    if expected_value is None:
                        assert field_wrapper.value is None
                        assert field_wrapper.timestamp is None
                        for indices in indices_list:
                            indexed_field_wrapper = indexed_field_wrappers[
                                (sensor_name, indices)
                            ]
                            assert indexed_field_wrapper.value is None
                            assert indexed_field_wrapper.timestamp is None
                        expected_location_str = ""
                    else:
                        expected_timestamp = topic_wrapper.data_cache[
                            sensor_name
                        ].private_sndStamp
                        assert field_wrapper.value == expected_value
                        assert field_wrapper.timestamp == expected_timestamp
                        for indices in indices_list:
                            indexed_field_wrapper = indexed_field_wrappers[
                                (sensor_name, indices)
                            ]
                            assert field_wrapper.value == expected_value
                            assert indexed_field_wrapper.timestamp == expected_timestamp
                        expected_location_str = location_str_dict[sensor_name]

                    # Test the get_value_descr method.
                    for bad_index in (-1, temperature_len, None):
                        with pytest.raises(ValueError):
                            field_wrapper.get_value_descr(index=bad_index)
                    # This assumes the values are separated by ", ";
                    # they are for this test, but not necessarily in general.
                    expected_location_arr = expected_location_str.split(", ")
                    for index in range(temperature_len):
                        value_descr = field_wrapper.get_value_descr(index)
                        assert field_wrapper.topic_descr in value_descr
                        if index < len(expected_location_arr):
                            assert expected_location_arr[index] in value_descr
                        else:
                            assert f"[{index}]" in value_descr

    async def test_constructor_errors(self):
        model = watcher.MockModel(enabled=True)
        array_field_name = "temperature"
        array_len = 16
        scalar_field_name = "timestamp"

        async with salobj.Controller(
            name="ESS", index=self.index
        ) as controller, salobj.Remote(
            domain=controller.domain,
            name="ESS",
            index=self.index,
            readonly=True,
            include=["temperature"],
        ) as remote:
            topic = remote.tel_temperature

            good_indices = (0,)  # safe for any array field

            # FilteredEssFieldWrapper: no such field_name
            for wrapper_class, indices_kwargs in (
                (watcher.FilteredEssFieldWrapper, dict()),
                (watcher.IndexedFilteredEssFieldWrapper, dict(indices=[0, 1, 2])),
            ):
                with self.subTest(wrapper_class=wrapper_class):
                    with pytest.raises(ValueError):
                        # Invalid field_name
                        wrapper_class(
                            model=model,
                            topic=topic,
                            sensor_name=1,
                            field_name="no_such_field",
                            **indices_kwargs,
                        )

            # IndexedFilteredEssFieldWrapper: scalar field not allowed
            with pytest.raises(ValueError):
                watcher.IndexedFilteredEssFieldWrapper(
                    model=model,
                    topic=topic,
                    sensor_name=1,
                    field_name=scalar_field_name,
                    indices=good_indices,
                )

            # IndexedFilteredEssFieldWrapper: indices must be in range
            for bad_indices in [(-1,), (0, array_len, 1)]:
                with pytest.raises(ValueError):
                    watcher.IndexedFilteredEssFieldWrapper(
                        model=model,
                        topic=topic,
                        sensor_name=1,
                        field_name=array_field_name,
                        indices=bad_indices,
                    )
