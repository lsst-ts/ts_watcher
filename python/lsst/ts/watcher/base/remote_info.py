# This file is part of ts_watcher.
#
# Developed for the LSST Data Management System.
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

__all__ = ["RemoteInfo"]

import collections


def as_tuple(seq):
    """Return a sequence as a tuple.

    Parameters
    ----------
    seq : `list` of [``any``] (optional)
        Sequence to convert.

    Raises
    ------
    ValueError
        If seq is not None or a sequence.
    """
    if seq is None:
        return ()
    if isinstance(seq, str):
        raise ValueError(f"{seq!r} is a str, not a sequence")
    if not isinstance(seq, collections.abc.Iterable):
        raise ValueError(f"{seq!r} is not a sequence")
    return tuple(seq)


class RemoteInfo:
    """Information about a remote SAL component.

    Parameters
    ----------
    name : `str`
        Name of SAL component.
    index : `int`
        SAL component index; use 0 if the component is not indexed.
    callback_names : `list` [`str`] (optional)
        Names of telemetry or topic names for which the rule is called
        when a sample is read. If None then no such topics.
        Each name must include prefix ``evt_`` or ``tel_``
        for event or telemetry.
        For example ["evt_FilterChangeInPosition", "evt_TrackingTarget"]
    poll_names : `list` [`str`] (optional)
        Names of telemetry or topic names for which are available to the rule,
        but do not trigger a callback. If None then no such topics.
        Each name must include prefix ``evt_`` or ``tel_``
        for event or telemetry.

    Raises
    ------
    ValueError
        If any name in ``callback_names`` or ``poll_names`` does not begin
        with ``evt_`` or ``tel_``.
    ValueError
        If the same name appears more than once in
        ``callback_names + poll_names``, in other words, more than once
        in either list or in both lists taken together.
    ValueError
        If no ``callback_names`` nor ``poll_names`` are specified.
    ValueError
        If ``index`` cannot be cast to an `int`.
    """

    def __init__(self, name, index, callback_names=None, poll_names=None):
        self.name = name
        self.index = int(index)
        self.callback_names = as_tuple(callback_names)
        self.poll_names = as_tuple(poll_names)
        if not self.callback_names and not self.poll_names:
            raise ValueError("Must specify at least one callback or poll name")
        if len(set(self.callback_names) | set(self.poll_names)) < len(
            self.callback_names
        ) + len(self.poll_names):
            raise ValueError(
                f"There are duplicates in callback_names={callback_names} "
                f"and poll_names={poll_names}"
            )
        invalid_names = [
            name
            for name in self.callback_names + self.poll_names
            if not (name.startswith("evt_") or name.startswith("tel_"))
        ]
        if invalid_names:
            raise ValueError(
                "All callback and poll names must beging with 'evt_' or 'tel_': "
                f"invalid names={invalid_names}"
            )

    @property
    def key(self):
        return (self.name, self.index)

    @property
    def topic_names(self):
        return self.callback_names + self.poll_names
