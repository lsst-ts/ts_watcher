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

import asynctest

from lsst.ts import salobj
from lsst.ts import watcher

STD_TIMEOUT = 5  # Max time to send/receive a topic (seconds)
LONG_TIMEOUT = 60  # Max Remote startup time (seconds)

index_gen = salobj.index_generator()


class RemoteWrapperTestCase(asynctest.TestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()
        self.index = next(index_gen)

    async def test_all_names(self):
        async with salobj.Domain() as domain:
            remote = salobj.Remote(
                domain=domain,
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
                self.assertFalse(hasattr(remote, name))

            wrapper = watcher.base.RemoteWrapper(remote=remote, topic_names=topic_names)
            desired_attr_name = (
                remote.salinfo.name.lower() + "_" + str(remote.salinfo.index)
            )
            self.assertEqual(wrapper.attr_name, desired_attr_name)

            # Check that all topics have been added
            for name in topic_names:
                self.assertTrue(hasattr(remote, name))

            wrapper_dir = set(dir(wrapper))
            self.assertTrue(set(topic_names).issubset(wrapper_dir))

            await asyncio.wait_for(remote.start(), timeout=LONG_TIMEOUT)

            # Check that the initial value for each topic is None.
            for name in topic_names:
                self.assertIsNone(getattr(wrapper, name))

            # Write one event and one telemetry topic
            evt_scalars_writer = salobj.topics.ControllerEvent(
                salinfo=remote.salinfo, name="scalars"
            )
            tel_scalars_writer = salobj.topics.ControllerTelemetry(
                salinfo=remote.salinfo, name="scalars"
            )
            evtint = -3
            telint = 47
            evt_scalars_writer.set_put(int0=evtint)
            tel_scalars_writer.set_put(int0=telint)

            # Wait for the read topics to read the data.
            await remote.evt_scalars.next(flush=False, timeout=STD_TIMEOUT)
            await remote.tel_scalars.next(flush=False, timeout=STD_TIMEOUT)

            # Verify that the wrapper produces the expected values.
            self.assertEqual(wrapper.evt_scalars.int0, evtint)
            self.assertEqual(wrapper.tel_scalars.int0, telint)

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
                self.assertFalse(hasattr(remote, name))

            evt_wrapper = watcher.base.RemoteWrapper(
                remote=remote, topic_names=event_names
            )
            tel_wrapper = watcher.base.RemoteWrapper(
                remote=remote, topic_names=telemetry_names
            )

            # Check that all topics have been added to the remote.
            for name in event_names + telemetry_names:
                self.assertTrue(hasattr(remote, name))

            # Check that the event wrapper has all the event names
            # and none of the telemetry names, and vice-versa.
            evt_wrapper_dir = set(dir(evt_wrapper))
            tel_wrapper_dir = set(dir(tel_wrapper))
            self.assertTrue(set(event_names).issubset(evt_wrapper_dir))
            self.assertTrue(set(telemetry_names).issubset(tel_wrapper_dir))
            self.assertEqual(set(event_names) & tel_wrapper_dir, set())
            self.assertEqual(set(telemetry_names) & evt_wrapper_dir, set())

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
                    with self.assertRaises(ValueError):
                        watcher.base.RemoteWrapper(
                            remote=remote, topic_names=bad_topic_names
                        )


if __name__ == "__main__":
    unittest.main()
