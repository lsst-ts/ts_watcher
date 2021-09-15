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
import pytest
import unittest

from lsst.ts import salobj
from lsst.ts import watcher
from lsst.ts.watcher.rules import DewPointFromHumidityWrapper

index_gen = salobj.index_generator()


class DewPointFromHumidityWrapperTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()
        self.index = next(index_gen)

    async def test_basics(self):
        async with salobj.Controller(
            name="ESS", index=self.index
        ) as controller, salobj.Remote(
            domain=controller.domain,
            name="ESS",
            index=self.index,
            readonly=True,
            include=["hx85a", "hx85ba"],
        ) as remote:
            for topic_name in ("tel_hx85a", "tel_hx85ba"):
                await self.check_basics(
                    controller=controller, remote=remote, topic_name=topic_name
                )

    async def check_basics(self, controller, remote, topic_name):
        model = watcher.MockModel(enabled=True)

        filter_field = "sensorName"

        # Value of filter_field used by the field wrapper
        this_filter_value = "this"
        # A different value of filter_Field that should be ignored
        # by the field wrapper.
        other_filter_value = "other"

        remote_topic = getattr(remote, topic_name)
        controller_topic = getattr(controller, topic_name)
        field_wrapper = DewPointFromHumidityWrapper(
            model=model,
            topic=remote_topic,
            filter_field=filter_field,
            filter_value=this_filter_value,
        )

        # Test field wrapper attributes
        assert field_wrapper.topic_wrapper is not None
        assert field_wrapper.filter_value == this_filter_value
        assert field_wrapper.nelts is None
        assert str(this_filter_value) in field_wrapper.descr
        assert field_wrapper.value is None
        assert field_wrapper.timestamp is None

        # Test that a TopicCallback was created and the wrapper added.
        assert isinstance(remote_topic.callback, watcher.TopicCallback)
        assert remote_topic.callback.topic_wrappers == [field_wrapper.topic_wrapper]

        # Test data from
        # doc/Dewpoint_Calculation_Humidity_Sensor_E.pdf
        # RH=10%, T=25°C -> Dew point = -8.77°C
        # RH=90%, T=50°C -> Dew point = 47.90°C
        # List of (data dict for the hx85a topic, expected dew point)
        dataList = [
            (dict(relativeHumidity=10, temperature=25), -8.77),
            (dict(relativeHumidity=90, temperature=50), 47.90),
        ]

        # Test the compute_dew_point static method
        for data_dict, desired_dew_point in dataList:
            dew_point = field_wrapper.compute_dew_point(
                relative_humidity=data_dict["relativeHumidity"],
                temperature=data_dict["temperature"],
            )
            assert dew_point == pytest.approx(desired_dew_point, abs=0.005)

        # Send data with a different filter value;
        # the field wrapper should ignore it
        for data_dict, desired_dew_point in dataList:
            data_dict = data_dict.copy()
            data_dict[filter_field] = other_filter_value
            controller_topic.set_put(**data_dict)
            await asyncio.sleep(0.001)
            assert field_wrapper.value is None
            assert field_wrapper.timestamp is None

        # Send data to this filter value and check results
        for data_dict, desired_dew_point in dataList:
            data_dict = data_dict.copy()
            data_dict[filter_field] = this_filter_value
            controller_topic.set_put(**data_dict)
            await asyncio.sleep(0.001)
            assert desired_dew_point == pytest.approx(field_wrapper.value, abs=0.005)
            assert field_wrapper.timestamp is not None
