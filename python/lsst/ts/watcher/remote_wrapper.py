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

__all__ = ["RemoteWrapper"]

from lsst.ts import salobj


class RemoteWrapper:
    """Simple access to the current value of a specified set of topics.

    The wrapper uses the same attribute names as `lsst.ts.salobj.Remote`,
    but the wrapper's attributes return the current value of the topic.
    For example `remote_wrapper.evt_summaryState` returns
    `remote.evt_summaryState.get()`.

    Parameters
    ----------
    remote : `lsst.ts.salobj.Remote`
        Remote to wrap.
    topic_names : `list` [`str`]
        List of names of topics to wrap, with an ``evt_`` or ``tel_`` prefix.

    Raises
    ------
    ValueError
        If a name in ``topic_names`` is neither the name of an event
        nor a telemetry topic.

    Notes
    -----
    The intent is to offer each `BaseRule` simple access to the current value
    of the topics it needs, while hiding access to other topics and to methods
    of topics that `BaseRule` should not use, such as ``next``.
    """

    def __init__(self, remote, topic_names):
        self.name = remote.salinfo.name
        self.index = remote.salinfo.index
        # A dict of topic attribute name: topic. For example:
        # "evt_summaryState": lsst.ts.salobj.RemoteEvent(...)
        self._topics = dict()
        event_names = frozenset(remote.salinfo.event_names)
        telemetry_names = frozenset(remote.salinfo.telemetry_names)
        for topic_name in topic_names:
            short_topic_name = topic_name[4:]
            if topic_name.startswith("evt_"):
                if short_topic_name not in event_names:
                    raise ValueError(f"Unknown event topic name {short_topic_name}")
                topic = getattr(remote, topic_name, None)
                if topic is None:
                    # create the topic and add it to the remote
                    topic = salobj.topics.RemoteEvent(remote.salinfo, short_topic_name)
                    setattr(remote, topic_name, topic)
                self._topics[topic_name] = topic
            elif topic_name.startswith("tel_"):
                if short_topic_name not in telemetry_names:
                    raise ValueError(f"Unknown telemetry topic name {short_topic_name}")
                topic = getattr(remote, topic_name, None)
                if topic is None:
                    # create the topic and add it to the remote
                    topic = salobj.topics.RemoteTelemetry(
                        remote.salinfo, short_topic_name
                    )
                    setattr(remote, topic_name, topic)
                self._topics[topic_name] = topic
            else:
                raise ValueError(
                    f"Unknown topic prefix in {topic_name:r}: must be 'tel_' or 'evt_'"
                )

    @property
    def attr_name(self):
        """Get the rule attribute name for this remote wrapper."""
        return f"{self.name.lower()}_{self.index}"

    def get_topic(self, name):
        """Return the appropriate `lsst.ts.salobj.ReadTopic`.

        Parameters
        ----------
        name : `str`
            Topic name, with the appropriate ``evt_`` or ``tel_`` prefix.
            Example: "evt_logLevel".

        Raises
        ------
        KeyError
            If the topic does not exist.
        """
        return self._topics[name]

    def has_topic(self, name):
        """Return True if this wrapper has the specifies topic.

        Parameters
        ----------
        name : `str`
            Topic name, with the appropriate ``evt_`` or ``tel_`` prefix.
            Example: "evt_logLevel".
        """
        return name in self._topics

    def __getattr__(self, name):
        """Get the current value for the specified topic.

        Parameters
        ----------
        name : `str`
            Topic name, with the appropriate ``evt_`` or ``tel_`` prefix.
            Example: "evt_logLevel".

        Raises
        ------
        RuntimeError
            If the Remote has not started.
        KeyError
            If the topic does not exist.
        """
        return self._topics[name].get()

    def __dir__(self):
        return dir(RemoteWrapper) + list(self._topics.keys())
