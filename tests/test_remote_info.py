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

import pytest
import unittest

from lsst.ts import watcher


class RemoteInfoTestCase(unittest.TestCase):
    def test_constructor_good(self):
        name = "SomeCsc"
        index = 99
        callback_names = ("evt_call1", "tel_call2")
        poll_names = ("tel_poll1", "evt_poll2", "evt_poll3")

        info1 = watcher.RemoteInfo(
            name=name, index=index, callback_names=callback_names, poll_names=poll_names
        )
        assert info1.name == name
        assert info1.index == index
        assert info1.callback_names == callback_names
        assert info1.poll_names == poll_names

        info2 = watcher.RemoteInfo(
            name=name, index=index, callback_names=callback_names, poll_names=None
        )
        assert info2.name == name
        assert info2.index == index
        assert info2.callback_names == callback_names
        assert info2.poll_names == ()

        info3 = watcher.RemoteInfo(
            name=name, index=index, callback_names=None, poll_names=poll_names
        )
        assert info3.name == name
        assert info3.index == index
        assert info3.callback_names == ()
        assert info3.poll_names == poll_names

    def test_constructor_error(self):
        name = "SomeCsc"
        index = 99
        callback_names = ("evt_call1", "tel_call2")
        poll_names = ("tel_poll1", "evt_poll2", "evt_poll3")

        # make sure the basic parameters are OK
        info = watcher.RemoteInfo(
            name=name, index=index, callback_names=callback_names, poll_names=poll_names
        )
        assert info.name == name

        # index must be castable to an integer
        with pytest.raises(ValueError):
            watcher.RemoteInfo(
                name=name,
                index="not_an_integer",
                callback_names=callback_names,
                poll_names=poll_names,
            )

        # must specify at least one callback or poll name
        with pytest.raises(ValueError):
            watcher.RemoteInfo(
                name=name, index=index, callback_names=None, poll_names=None
            )

        with pytest.raises(ValueError):
            watcher.RemoteInfo(name=name, index=index, callback_names=(), poll_names=())

        # all callback and poll names must start with "evt_" or "tel_"
        with pytest.raises(ValueError):
            watcher.RemoteInfo(
                name=name,
                index=index,
                callback_names=["call1", "tel_call1"],
                poll_names=poll_names,
            )

        with pytest.raises(ValueError):
            watcher.RemoteInfo(
                name=name,
                index=index,
                callback_names=callback_names,
                poll_names=["evt_poll1", "poll2"],
            )

        # must have no overlapping callback or poll names
        with pytest.raises(ValueError):
            watcher.RemoteInfo(
                name=name,
                index=index,
                callback_names=["evt_call1", "evt_call1", "evt_call2"],
                poll_names=None,
            )

        with pytest.raises(ValueError):
            watcher.RemoteInfo(
                name=name,
                index=index,
                callback_names=None,
                poll_names=["evt_poll1", "evt_poll2", "evt_poll2"],
            )

        with pytest.raises(ValueError):
            watcher.RemoteInfo(
                name=name,
                index=index,
                callback_names=["name1", "evt_call2"],
                poll_names=["name1", "evt_poll2"],
            )

        with pytest.raises(ValueError):
            watcher.RemoteInfo(
                name=name,
                index=index,
                callback_names=["name1", "evt_call2"],
                poll_names=["name1", "evt_poll2"],
            )
