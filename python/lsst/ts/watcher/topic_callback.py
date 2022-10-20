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

__all__ = ["get_topic_key", "TopicCallback"]

import asyncio


def get_topic_key(topic):
    """Compute the key unique to a topic.

    Parameters
    ----------
    topic : `lsst.ts.salobj.ReadTopic`
        Topic.

    Returns
    -------
    topic_key : `tuple`
        Topic key: (SAL component name, SAL index, topic attribute name)
        where topic attribute name includes the ``tel_`` or ``evt_`` prefix.
        Example: ``("ESS", 5, "tel_temperature")``
    """
    return (topic.salinfo.name, topic.salinfo.index, topic.attr_name)


class TopicCallback:
    """Call rules and/or wrapper callbacks when a topic receives data.

    Parameters
    ----------
    topic : `salobj.ReadTopic`
        Topic to monitor.
    rule : `BaseRule` or `None`
        Rule to call, or None if none.
        The rule is called with two keyword arguments:

        * data: the new data
        * topic_callbacck: this instance
    model : `Model`
        Watcher model. Used by `__call__`
        to check if the model is enabled.

    Attributes
    ----------
    rules : `dict`
        Dict of rule name: rule.
    topic_wrappers:
        List of topic wrappers.
    model : `Model`
        The Watcher model.
    topic_key : `tuple`
        The topic key computed by get_topic_key.
    call_event : `asyncio.Event`
        An event that is set whenever this topic callback's
        ``__call__`` method finishes normally (without raising an exception).
        Intended for unit tests, which may clear this event
        and then wait for it to be set.
    """

    def __init__(self, topic, rule, model):
        self.call_event = asyncio.Event()
        self._topic = topic
        self.topic_wrappers = list()
        if rule is None:
            self.rules = {}
        else:
            self.rules = {rule.name: rule}
        self.model = model
        self._topic.callback = self
        self.topic_key = get_topic_key(self._topic)

    @property
    def attr_name(self):
        """Get the topic name, with an ``evt_`` or ``tel_`` prefix.

        This is the name of the wrapped topic attribute in `RemoteWrapper`.
        """
        return self._topic.attr_name

    @property
    def remote_name(self):
        """Get the name of the remote."""
        return self._topic.salinfo.name

    @property
    def remote_index(self):
        """Get the SAL index of the remote."""
        return self._topic.salinfo.index

    def add_topic_wrapper(self, wrapper):
        """Add a topic wrapper, or other non-rule callable.

        Parameters
        ----------
        wrapper : `callable`
            A TopicWrapper or other function that will be called with
            two keyword arguments:

            * data: the new data
            * topic_callbacck: this instance

        Wrapper callbacks are called before rule callbacks.
        """
        self.topic_wrappers.append(wrapper)

    def add_rule(self, rule):
        """Add a rule.

        Parameters
        ----------
        rule : `BaseRule`
            Rule to add.
        """
        if rule.name in self.rules:
            raise ValueError(f"A rule named {rule.name} already exists")
        self.rules[rule.name] = rule

    async def __call__(self, data):
        if not self.model.enabled:
            return
        for wrapper in self.topic_wrappers:
            try:
                wrapper(data=data, topic_callback=self)
            except Exception:
                self._topic.log.exception(
                    f"Error calling wrapper {wrapper} with data {data!s}"
                )
                pass
        for rule in self.rules.values():
            try:
                severity, reason = rule(data=data, topic_callback=self)
                await rule.alarm.set_severity(severity=severity, reason=reason)
            except Exception:
                self._topic.log.exception(
                    f"Error calling rule {rule} with data {data!s}"
                )
                pass
        self.call_event.set()
