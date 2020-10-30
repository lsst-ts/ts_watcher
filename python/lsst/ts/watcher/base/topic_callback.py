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

__all__ = ["TopicCallback"]


class TopicCallback:
    """Call one or more rules when a salobj topic receives a sample.

    The rule is called with one argument: this topic callback.

    Parameters
    ----------
    topic : `salobj.ReadTopic`
        Topic to monitor.
    rule : `BaseRule`
        Rule to call.
    model : `Model`
        Watcher model. Used by `__call__`
        to check if the model is enabled.
    """

    def __init__(self, topic, rule, model):
        self._topic = topic
        self.rules = {rule.name: rule}
        self.model = model
        self._topic.callback = self

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

    def get(self):
        """Get the current value of the topic.

        This is provided so that code in `Rule.__call__` can easily get
        the current value of the topic that triggered the call.
        """
        return self._topic.get()

    def __call__(self, value):
        if not self.model.enabled:
            return
        for rule in self.rules.values():
            try:
                severity, reason = rule(self)
                rule.alarm.set_severity(severity=severity, reason=reason)
            except Exception:
                self._topic.log.exception(
                    f"Error calling rule {rule.name} with value {value!s}"
                )
                pass
