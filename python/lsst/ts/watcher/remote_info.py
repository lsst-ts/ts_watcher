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

__all__ = ["RemoteInfo"]

import collections


def as_tuple(seq):
    """Return a sequence as a tuple.

    Parameters
    ----------
    seq : `list` of [``any``], optional
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
    callback_names : `list` [`str`], optional
        Names of telemetry or event topics for which the rule is called
        when a sample is read. If None then no such topics.
        Each name must include prefix ``evt_`` or ``tel_``
        for event or telemetry.
        For example ["evt_FilterChangeInPosition", "evt_TrackingTarget"]
    poll_names : `list` [`str`], optional
        Names of telemetry or event topics which are available to the rule,
        but do not trigger a rule callback. If None then no such topics.
        Each name must include prefix ``evt_`` or ``tel_``
        for event or telemetry.
    index_required : `bool`, optional
        If the component is indexed, is a non-zero index required?
        Defaults to True, since it is rare for a rule to be able to
        handle more than one instance of a CSC.

    Attributes
    ----------
    name : `str`
        Name of SAL component.
    index : `int`
        SAL component index; use 0 if the component is not indexed.
    callback_names : `tuple` [`str`]
        The ``callback_names`` argument converted to a tuple;
        an empty tuple if the argument is None.
    poll_names : `tuple` [`str`]
        The ``poll_names`` argument converted to a tuple;
        an empty tuple if the argument is None.

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

    def __init__(
        self, name, index, callback_names=None, poll_names=None, index_required=True
    ):
        self.name = name
        self.index = int(index)
        self.callback_names = as_tuple(callback_names)
        self.poll_names = as_tuple(poll_names)
        self.index_required = index_required
        all_names = self.topic_names
        if not all_names:
            raise ValueError("No topic names found callback_names or poll_names")
        if len(all_names) > len(set(all_names)):
            duplicates = list()
            seen = set()
            for name in all_names:
                if name in seen:
                    duplicates.append(name)
                else:
                    seen.add(name)
            raise ValueError(
                f"Topic names {duplicates} appear more than once "
                "in callback_names and/or poll_names"
            )
        invalid_names = [
            name
            for name in all_names
            if not (name.startswith("evt_") or name.startswith("tel_"))
        ]
        if invalid_names:
            raise ValueError(
                f"Invalid topic names {invalid_names} in callback_names and/or "
                "poll_names; all topic names must begin with 'evt_' or 'tel_'"
            )

    @property
    def key(self):
        return (self.name, self.index)

    @property
    def topic_names(self):
        """Get all topic names: callback_names + poll_names."""
        return self.callback_names + self.poll_names
