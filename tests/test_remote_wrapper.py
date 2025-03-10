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

STD_TIMEOUT = 5  # Max time to send/receive a topic (seconds)
LONG_TIMEOUT = 60  # Max Remote startup time (seconds)

# Isolate the test by selecting a unit index range
# for the Test component.
index_gen = utils.index_generator(imin=1234)


class RemoteWrapperTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()
        self.index = next(index_gen)

    async def test_all_names(self):
        async with salobj.Controller(
            name="Test", index=self.index, write_only=True
        ) as controller:
            remote = salobj.Remote(
                domain=controller.salinfo.domain,
                name="Test",
                index=self.index,
                readonly=True,
                include=(),
                start=False,
            )
            topic_names = [f"evt_{name}" for name in remote.salinfo.event_names]
            topic_names += [f"tel_{name}" for name in remote.salinfo.telemetry_names]

            # Check that no topics have been added yet
            for name in topic_names:
                assert not hasattr(remote, name)

            wrapper = watcher.RemoteWrapper(remote=remote, topic_names=topic_names)
            desired_attr_name = (
                remote.salinfo.name.lower() + "_" + str(remote.salinfo.index)
            )
            assert wrapper.attr_name == desired_attr_name

            # Check that all topics have been added
            for name in topic_names:
                assert hasattr(remote, name)

            wrapper_dir = set(dir(wrapper))
            assert set(topic_names).issubset(wrapper_dir)

            await asyncio.wait_for(remote.start(), timeout=LONG_TIMEOUT)

            # Check that the initial value for each topic is None
            # (except a few topics that Controller writes).
            for name in topic_names:
                if name in {"evt_authList", "evt_logLevel", "evt_logMessage"}:
                    continue
                assert getattr(wrapper, name) is None

            # Write one event and one telemetry topic
            evtint = -3
            telint = 47
            await controller.evt_scalars.set_write(int0=evtint)
            await controller.tel_scalars.set_write(int0=telint)

            # Wait for the read topics to read the data.
            await remote.evt_scalars.next(flush=False, timeout=STD_TIMEOUT)
            await remote.tel_scalars.next(flush=False, timeout=STD_TIMEOUT)

            # Verify that the wrapper produces the expected values.
            assert wrapper.evt_scalars.int0 == evtint
            assert wrapper.tel_scalars.int0 == telint

    async def test_some_names(self):
        """Test wrappers that wrap a subset of names."""
        async with salobj.Domain() as domain:
            remote = salobj.Remote(
                domain=domain,
                name="Test",
                index=self.index,
                readonly=True,
                include=(),
                start=False,
            )
            event_names = [f"evt_{name}" for name in remote.salinfo.event_names]
            telemetry_names = [f"tel_{name}" for name in remote.salinfo.telemetry_names]

            # Check that no topics have been added yet.
            for name in event_names + telemetry_names:
                assert not hasattr(remote, name)

            evt_wrapper = watcher.RemoteWrapper(remote=remote, topic_names=event_names)
            tel_wrapper = watcher.RemoteWrapper(
                remote=remote, topic_names=telemetry_names
            )

            # Check that all topics have been added to the remote.
            for name in event_names + telemetry_names:
                assert hasattr(remote, name)

            # Check that the event wrapper has all the event names
            # and none of the telemetry names, and vice-versa.
            evt_wrapper_dir = set(dir(evt_wrapper))
            tel_wrapper_dir = set(dir(tel_wrapper))
            assert set(event_names).issubset(evt_wrapper_dir)
            assert set(telemetry_names).issubset(tel_wrapper_dir)
            assert set(event_names) & tel_wrapper_dir == set()
            assert set(telemetry_names) & evt_wrapper_dir == set()

            for evt_name in event_names:
                assert evt_wrapper.has_topic(evt_name)
                assert not tel_wrapper.has_topic(evt_name)
                topic = evt_wrapper.get_topic(evt_name)
                assert isinstance(topic, salobj.topics.RemoteEvent)
            for tel_name in telemetry_names:
                assert tel_wrapper.has_topic(tel_name)
                assert not evt_wrapper.has_topic(tel_name)
                topic = tel_wrapper.get_topic(tel_name)
                assert isinstance(topic, salobj.topics.RemoteTelemetry)

    async def test_constructor_error(self):
        async with salobj.Domain() as domain:
            remote = salobj.Remote(
                domain=domain, name="Test", index=self.index, readonly=True, start=False
            )

            for bad_topic_names in (
                ["noprefix"],
                ["evb_incorrectprefix"],
                ["evt_nosuchevent"],
                ["tel_nosuchtelemetry"],
                ["evt_summaryState", "evt_nosuchevent"],
                ["tel_scalars", "tel_nosuchtelemetry"],
            ):
                with self.subTest(bad_topic_names=bad_topic_names):
                    with pytest.raises(ValueError):
                        watcher.RemoteWrapper(
                            remote=remote, topic_names=bad_topic_names
                        )
