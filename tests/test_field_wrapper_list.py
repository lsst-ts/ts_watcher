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
import math
import unittest

import numpy as np
import numpy.random

from lsst.ts import salobj
from lsst.ts import utils
from lsst.ts import watcher

index_gen = utils.index_generator()


class FieldWrapperListTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()
        self.index = next(index_gen)

    async def test_basics(self):
        model = watcher.MockModel(enabled=True)
        filter_field = "sensorName"
        scalar_data_field = "relativeHumidity"
        array_data_field = "temperature"
        array_len = 16
        nan_array_len = 2
        # Indices to data; the last index points to NaN
        # and the rest to valid data.
        indices = (1, 2, array_len - nan_array_len - 1, array_len - 1)
        # Indices to valid (non-nan) data
        nonnan_indices = indices[:-1]

        # Value of filter_field used by the FieldWrapperList
        this_filter_value = "this"
        # A different value of filter_Field that should be ignored
        # by the FieldWrapperList.
        other_filter_value = "other"

        async with salobj.Controller(
            name="ESS", index=self.index
        ) as controller, salobj.Remote(
            domain=controller.domain,
            name="ESS",
            index=self.index,
            readonly=True,
            include=["hx85a", "temperature"],
        ) as remote:
            remote_scalar_topic = remote.tel_hx85a
            remote_array_topic = remote.tel_temperature
            controller_scalar_topic = controller.tel_hx85a
            controller_array_topic = controller.tel_temperature

            array_len = len(getattr(remote_array_topic.DataType(), array_data_field))
            # Make only a subset of the array be valid
            valid_array_len = array_len - nan_array_len
            assert valid_array_len > 0

            rng = numpy.random.default_rng(seed=47)

            def random_scalar():
                """Return a random float32."""
                return rng.random(1, dtype=np.float32)[0]

            def random_array():
                """Return a random list of valid_array_len float32."""
                return list(rng.random(valid_array_len, dtype=np.float32))

            async def write_scalar(filter_value):
                """Write random data for the scalar_data_field of the
                scalar topic and return that data.
                """
                scalar_data = random_scalar()
                data_dict = {filter_field: filter_value, scalar_data_field: scalar_data}
                controller_scalar_topic.set_put(**data_dict)
                await asyncio.sleep(0.001)
                return scalar_data

            async def write_array(filter_value):
                """Write random data for the array_data_field of the
                array topic and return that data.
                """
                array_data = random_array() + [math.nan] * nan_array_len
                data_dict = {filter_field: filter_value, array_data_field: array_data}
                controller_array_topic.set_put(**data_dict)
                await asyncio.sleep(0.001)
                return array_data

            wrapper_list = watcher.FieldWrapperList()

            # Scalar field wrapper
            scalar_field_wrapper = watcher.FilteredEssFieldWrapper(
                model=model,
                topic=remote_scalar_topic,
                sensor_name=this_filter_value,
                field_name=scalar_data_field,
            )
            wrapper_list.add_wrapper(scalar_field_wrapper)

            # Array field wrapper; all elements
            array_field_wrapper = watcher.FilteredEssFieldWrapper(
                model=model,
                topic=remote_array_topic,
                sensor_name=this_filter_value,
                field_name=array_data_field,
            )
            wrapper_list.add_wrapper(array_field_wrapper)

            # Array field wrapper; a subset of elements
            indexed_field_wrapper = watcher.IndexedFilteredEssFieldWrapper(
                model=model,
                topic=remote_array_topic,
                sensor_name=this_filter_value,
                field_name=array_data_field,
                indices=indices,
            )
            wrapper_list.add_wrapper(indexed_field_wrapper)

            data = wrapper_list.get_data()
            assert data == []

            # Write scalar and array data for the other value of filter_field;
            # the field wrapper list should ignore it.
            await write_scalar(other_filter_value)
            await write_array(other_filter_value)

            data = wrapper_list.get_data()
            assert data == []

            # Write scalar data for this value of filter_field;
            # that data should appear in the output.
            scalar_data = await write_scalar(this_filter_value)

            data = wrapper_list.get_data()
            assert len(data) == 1
            assert data[0] == (scalar_data, scalar_field_wrapper, None)

            # Send data for the array;
            # Now all values should be present
            array_data = await write_array(this_filter_value)
            assert len(array_data) == array_len  # paranoia
            data = wrapper_list.get_data()
            # We expect the following data (in order):
            # * the scalar, from the scalar wrapper
            # * the full array, from the array wrapper
            # * the indices from the full array, from the indexed wrapper
            expected_data = [(scalar_data, scalar_field_wrapper, None)]
            expected_data += [
                (array_data[i], array_field_wrapper, i) for i in range(valid_array_len)
            ]
            expected_data += [
                (array_data[i], indexed_field_wrapper, i) for i in nonnan_indices
            ]
            assert len(data) == len(expected_data)
            assert data == expected_data

            # Test omit_nan=False argument to get_data
            data = wrapper_list.get_data(omit_nan=False)
            # We expect the following data (in order):
            # * the scalar, from the scalar wrapper
            # * the full array, from the array wrapper
            # * the indices from the full array, from the indexed wrapper
            expected_data = [(scalar_data, scalar_field_wrapper, None)]
            expected_data += [
                (array_data[i], array_field_wrapper, i) for i in range(array_len)
            ]
            expected_data += [
                (array_data[i], indexed_field_wrapper, i) for i in indices
            ]
            assert len(data) == len(expected_data)
            for item1, item2 in zip(data, expected_data):
                if math.isnan(item1[0]):
                    assert math.isnan(item2[0])
                    assert item1[1:] == item2[1:]
                else:
                    assert item1 == item2

            # Test max_age argument to get_data
            # Rather waiting a long time and then publishing some data,
            # hack this by manually changing the timestamp field
            # of the wrappers. Use some margin to avoid problems
            # from the non-monotonic clock on Docker on macOS.
            margin = 0.2

            max_age = 5
            array_field_wrapper.timestamp = utils.current_tai() - max_age - margin
            data = wrapper_list.get_data(max_age=max_age)
            # We expect the following data (in order):
            # * the scalar, from the scalar wrapper
            # * the indices from the full array, from the indexed wrapper
            expected_data = [(scalar_data, scalar_field_wrapper, None)]
            expected_data += [
                (array_data[i], indexed_field_wrapper, i) for i in nonnan_indices
            ]
            assert len(data) == len(expected_data)
            assert data == expected_data
