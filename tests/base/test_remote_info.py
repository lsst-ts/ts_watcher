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

import unittest

from lsst.ts import watcher


class RemoteInfoTestCase(unittest.TestCase):
    def test_constructor_good(self):
        name = "SomeCsc"
        index = 99
        callback_names = ("evt_call1", "tel_call2")
        poll_names = ("tel_poll1", "evt_poll2", "evt_poll3")

        info1 = watcher.base.RemoteInfo(
            name=name, index=index, callback_names=callback_names, poll_names=poll_names
        )
        self.assertEqual(info1.name, name)
        self.assertEqual(info1.index, index)
        self.assertEqual(info1.callback_names, callback_names)
        self.assertEqual(info1.poll_names, poll_names)

        info2 = watcher.base.RemoteInfo(
            name=name, index=index, callback_names=callback_names, poll_names=None
        )
        self.assertEqual(info2.name, name)
        self.assertEqual(info2.index, index)
        self.assertEqual(info2.callback_names, callback_names)
        self.assertEqual(info2.poll_names, ())

        info3 = watcher.base.RemoteInfo(
            name=name, index=index, callback_names=None, poll_names=poll_names
        )
        self.assertEqual(info3.name, name)
        self.assertEqual(info3.index, index)
        self.assertEqual(info3.callback_names, ())
        self.assertEqual(info3.poll_names, poll_names)

    def test_constructor_error(self):
        name = "SomeCsc"
        index = 99
        callback_names = ("evt_call1", "tel_call2")
        poll_names = ("tel_poll1", "evt_poll2", "evt_poll3")

        # make sure the basic parameters are OK
        info = watcher.base.RemoteInfo(
            name=name, index=index, callback_names=callback_names, poll_names=poll_names
        )
        self.assertEqual(info.name, name)

        # index must be castable to an integer
        with self.assertRaises(ValueError):
            watcher.base.RemoteInfo(
                name=name,
                index="not_an_integer",
                callback_names=callback_names,
                poll_names=poll_names,
            )

        # must specify at least one callback or poll name
        with self.assertRaises(ValueError):
            watcher.base.RemoteInfo(
                name=name, index=index, callback_names=None, poll_names=None
            )

        with self.assertRaises(ValueError):
            watcher.base.RemoteInfo(
                name=name, index=index, callback_names=(), poll_names=()
            )

        # all callback and poll names must start with "evt_" or "tel_"
        with self.assertRaises(ValueError):
            watcher.base.RemoteInfo(
                name=name,
                index=index,
                callback_names=["call1", "tel_call1"],
                poll_names=poll_names,
            )

        with self.assertRaises(ValueError):
            watcher.base.RemoteInfo(
                name=name,
                index=index,
                callback_names=callback_names,
                poll_names=["evt_poll1", "poll2"],
            )

        # must have no overlapping callback or poll names
        with self.assertRaises(ValueError):
            watcher.base.RemoteInfo(
                name=name,
                index=index,
                callback_names=["evt_call1", "evt_call1", "evt_call2"],
                poll_names=None,
            )

        with self.assertRaises(ValueError):
            watcher.base.RemoteInfo(
                name=name,
                index=index,
                callback_names=None,
                poll_names=["evt_poll1", "evt_poll2", "evt_poll2"],
            )

        with self.assertRaises(ValueError):
            watcher.base.RemoteInfo(
                name=name,
                index=index,
                callback_names=["name1", "evt_call2"],
                poll_names=["name1", "evt_poll2"],
            )

        with self.assertRaises(ValueError):
            watcher.base.RemoteInfo(
                name=name,
                index=index,
                callback_names=["name1", "evt_call2"],
                poll_names=["name1", "evt_poll2"],
            )


if __name__ == "__main__":
    unittest.main()
