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
from lsst.ts import watcher

index_gen = salobj.index_generator()


class FilteredFieldWrapperTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()
        self.index = next(index_gen)

    async def test_scalar_field(self):
        """Test `FilteredFieldWrapper` with a scalar field."""
        model = watcher.MockModel(enabled=True)
        filter_field = "sensorName"
        data_field = "temperature"

        filter_values = ["one", "two"]
        # Dict of filter_value: FilteredFieldWrapper
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
            for i, filter_value in enumerate(filter_values):
                field_wrapper = watcher.FilteredFieldWrapper(
                    model=model,
                    topic=topic,
                    filter_field=filter_field,
                    filter_value=filter_value,
                    field_name=data_field,
                )
                field_wrappers[filter_value] = field_wrapper

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
                assert field_wrapper.filter_value == filter_value
                assert field_wrapper.nelts is None
                assert str(filter_value) in field_wrapper.descr
                assert field_wrapper.value is None
                assert field_wrapper.timestamp is None

            rng = numpy.random.default_rng(seed=47)

            def random_float():
                """Return a random float32."""
                return rng.random(1, dtype=np.float32)[0]

            # Test field callback handling
            filter_cycle = itertools.cycle(filter_values)
            data_dict_list = [
                {filter_field: next(filter_cycle), data_field: random_float()}
                for i in range(5)
            ]
            # Dict of filter_value: expected field wrapper value
            expected_values = {value: None for value in filter_values}
            for data_dict in data_dict_list:
                filter_value = data_dict[filter_field]
                expected_values[filter_value] = data_dict[data_field]
                controller.tel_hx85a.set_put(**data_dict)
                await asyncio.sleep(0.001)
                for filter_value in filter_values:
                    if expected_values[filter_value] is None:
                        assert field_wrappers[filter_value].value is None
                        assert field_wrappers[filter_value].timestamp is None
                    else:
                        assert (
                            field_wrappers[filter_value].value
                            == expected_values[filter_value]
                        )
                        expected_timestamp = topic_wrapper.data_cache[
                            filter_value
                        ].private_sndStamp
                        assert (
                            field_wrappers[filter_value].timestamp == expected_timestamp
                        )

    async def test_array_field(self):
        """Test `FilteredFieldWrapper` and `IndexedFilteredFieldWrapper` with
        an array field.
        """
        model = watcher.MockModel(enabled=True)
        filter_field = "sensorName"
        data_field = "temperature"

        filter_values = ["one", "two"]

        # Dict of filter_value: FilteredFieldWrapper
        field_wrappers = dict()
        # Dict of (filter_value, indices): IndexedFilteredFieldWrapper
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

            # Note: there is no difference between
            # IndexedFilteredFieldWrapper instances with different indices
            # beyond the value of the ``indices`` attribute.
            # These choices test whether indices at the extremes are allowed.
            indices_list = [
                (0,),
                (1, temperature_len - 1, 3, -2),
                (1, -temperature_len),
            ]

            topic_wrapper = None
            for i, filter_value in enumerate(filter_values):
                field_wrapper = watcher.FilteredFieldWrapper(
                    model=model,
                    topic=topic,
                    filter_field=filter_field,
                    filter_value=filter_value,
                    field_name=data_field,
                )
                field_wrappers[filter_value] = field_wrapper

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
                assert field_wrapper.filter_value == filter_value
                assert field_wrapper.nelts == temperature_len
                assert str(filter_value) in field_wrapper.descr
                assert field_wrapper.value is None

                for indices in indices_list:
                    indexed_field_wrapper = watcher.IndexedFilteredFieldWrapper(
                        model=model,
                        topic=topic,
                        filter_field=filter_field,
                        filter_value=filter_value,
                        field_name=data_field,
                        indices=indices,
                    )
                    indexed_field_wrappers[
                        (filter_value, indices)
                    ] = indexed_field_wrapper

                    # Test indexed field wrapper attributes
                    assert indexed_field_wrapper.topic_wrapper is topic_wrapper
                    assert indexed_field_wrapper.filter_value == filter_value
                    assert indexed_field_wrapper.nelts == temperature_len
                    assert indexed_field_wrapper.indices == indices
                    assert str(filter_value) in indexed_field_wrapper.descr
                    assert indexed_field_wrapper.value is None

            # Test field callback handling
            rng = numpy.random.default_rng(seed=29)

            def random_floats():
                """Return a list of temerature_len random float32."""
                return list(rng.random(temperature_len, dtype=np.float32))

            filter_cycle = itertools.cycle(filter_values)
            data_dict_list = [
                {filter_field: next(filter_cycle), data_field: random_floats()}
                for i in range(5)
            ]
            # Dict of filter_value: expected field wrapper value
            expected_values = {value: None for value in filter_values}
            for data_dict in data_dict_list:
                filter_value = data_dict[filter_field]
                expected_values[filter_value] = data_dict[data_field]
                controller.tel_temperature.set_put(**data_dict)
                await asyncio.sleep(0.001)
                for filter_value in filter_values:
                    expected_value = expected_values[filter_value]
                    if expected_value is None:
                        field_wrapper = field_wrappers[filter_value]
                        assert field_wrapper.value is None
                        assert field_wrapper.timestamp is None
                        for indices in indices_list:
                            indexed_field_wrapper = indexed_field_wrappers[
                                (filter_value, indices)
                            ]
                            assert indexed_field_wrapper.value is None
                            assert indexed_field_wrapper.timestamp is None
                    else:
                        expected_timestamp = topic_wrapper.data_cache[
                            filter_value
                        ].private_sndStamp

                        field_wrapper = field_wrappers[filter_value]
                        assert field_wrapper.value == expected_value
                        assert field_wrapper.timestamp == expected_timestamp
                        for indices in indices_list:
                            indexed_field_wrapper = indexed_field_wrappers[
                                (filter_value, indices)
                            ]
                            assert field_wrapper.value == expected_value
                            assert indexed_field_wrapper.timestamp == expected_timestamp

    async def test_constructor_errors(self):
        model = watcher.MockModel(enabled=True)
        filter_field = "sensorName"

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

            good_indices = (0,)  # safe for any array field

            # No such field_name
            with pytest.raises(ValueError):
                watcher.FilteredFieldWrapper(
                    model=model,
                    topic=topic,
                    filter_field=filter_field,
                    filter_value=1,
                    field_name="no_such_field",
                )

            with pytest.raises(ValueError):
                watcher.IndexedFilteredFieldWrapper(
                    model=model,
                    topic=topic,
                    filter_field=filter_field,
                    filter_value=1,
                    field_name="no_such_field",
                    indices=good_indices,
                )

            # Scalar field
            with pytest.raises(ValueError):
                watcher.IndexedFilteredFieldWrapper(
                    model=model,
                    topic=topic,
                    filter_field=filter_field,
                    filter_value=1,
                    field_name="timestamp",
                    indices=good_indices,
                )

            # Index out of range (the "temperature" field has 16 values)
            for bad_indices in [(16,), (0, 16, 1), (-17,)]:
                with pytest.raises(ValueError):
                    watcher.IndexedFilteredFieldWrapper(
                        model=model,
                        topic=topic,
                        filter_field=filter_field,
                        filter_value=1,
                        field_name="position",
                        indices=bad_indices,
                    )
