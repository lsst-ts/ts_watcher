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

__all__ = ["get_rule_class", "Model"]

import asyncio
import re
import types

from lsst.ts import salobj
from . import base
from . import rules


def get_rule_class(classname):
    """Get a rule class given its name.

    Parameters
    ----------
    classname : `str`
        Rule class name relative to the rules module, with no leading ".".
        For example specify ``"test.NoConfig"`` for the rule
        ``lsst.ts.watcher.rules.test.NoConfig``.
    """
    names = classname.split(".")
    try:
        item = rules
        for item_name in names:
            item = getattr(item, item_name)
        return item
    except AttributeError as e:
        raise ValueError(f"Rule class {classname!r} not found") from e


class Model:
    """Watcher model: constructs and manages rules and alarms.

    Parameters
    ----------
    domain : `lsst.ts.salobj.Domain`
        DDS Domain.
    config : `types.SimpleNamespace`
        Watcher configuration validated against the Watcher schema.
    alarm_callback : ``callable`` (optional)
        Function to call when an alarm changes state.
        It receives one argument: the alarm.
        If None then no callback occurs.
    """
    def __init__(self, domain, config, alarm_callback=None):
        self.domain = domain
        self.alarm_callback = alarm_callback

        self._enabled = False
        self.enable_task = salobj.make_done_future()

        # dict of (sal_component_name, sal_index): lsst.ts.salobj.Remote
        self.remotes = dict()
        """A dict of (sal_component_name, sal_index): lsst.ts.salobj.Remote.
        """

        # dict of rule_name: Rule
        self.rules = dict()
        """A dict of rule_name: Rule.
        """

        # convert the name of each disabled sal component from a string
        # in the form ``name`` or ``name:index`` to a tuple ``(name, index)``.
        config.disabled_sal_components = [salobj.name_to_name_index(name)
                                          for name in config.disabled_sal_components]
        self.config = config

        # make the rules
        for ruledata in self.config.rules:
            ruleclassname = ruledata["classname"]
            ruleclass = get_rule_class(ruleclassname)
            try:
                ruleschema = ruleclass.get_schema()
                validator = salobj.DefaultingValidator(ruleschema)
            except Exception as e:
                raise ValueError(f"Schema for rule class {ruleclassname} not valid") from e
            for i, ruleconfig_dict in enumerate(ruledata["configs"]):
                try:
                    full_ruleconfig_dict = validator.validate(ruleconfig_dict)
                    ruleconfig = types.SimpleNamespace(**full_ruleconfig_dict)
                except Exception as e:
                    raise ValueError(f"Config {i+1} for rule class {ruleclassname} not valid: "
                                     f"config={ruleconfig_dict}") from e
                rule = ruleclass(config=ruleconfig)
                if rule.is_usable(disabled_sal_components=config.disabled_sal_components):
                    self.add_rule(rule)

        # accumulate a list of topics that have callback functions
        self._topics_with_callbacks = list()
        for remote in self.remotes.values():
            for name in dir(remote):
                if name[0:4] in ("evt_", "tel_"):
                    topic = getattr(remote, name)
                    if topic.callback is not None:
                        self._topics_with_callbacks.append(topic)

        self.start_task = asyncio.ensure_future(self.start())

    @property
    def enabled(self):
        """Get or set the enabled state of the Watcher model.
        """
        return self._enabled

    def enable(self):
        """Enable the model. A no-op if already enabled.
        """
        if self._enabled:
            return
        self._enabled = True
        callback_coros = []
        for rule in self.rules.values():
            rule.alarm.reset()
            rule.start()
        for topic in self._topics_with_callbacks:
            data = topic.get(flush=False)
            if data is not None:
                callback_coros.append(topic._run_callback(data))
        self.enable_task = asyncio.ensure_future(asyncio.gather(*callback_coros))

    def disable(self):
        """Disable the model. A no-op if already disabled.
        """
        if not self._enabled:
            return
        self._enabled = False
        self.enable_task.cancel()

    async def start(self):
        """Start all remotes."""
        await asyncio.gather(*[remote.start() for remote in self.remotes.values()])

    async def close(self):
        """Stop rules and close remotes.
        """
        for rule in self.rules.values():
            rule.alarm.close()
        self.disable()
        await asyncio.gather(*[remote.close() for remote in self.remotes.values()])

    def acknowledge_alarm(self, name, severity, user):
        """Acknowledge one or more alarms.

        Parameters
        ----------
        name : `str`
            Regular expression for alarm name(s) to acknowledge.
        severity : `lsst.ts.idl.enums.Watcher.AlarmSeverity` or `int`
            Severity to acknowledge. If the severity goes above
            this level the alarm will unacknowledge itself.
        user : `str`
            Name of user; used to set acknowledged_by.
        """
        for rule in self.get_rules(name):
            rule.alarm.acknowledge(severity=severity, user=user)

    def add_rule(self, rule):
        """Add a rule.

        Parameters
        ----------
        rule : `BaseRule`
            Rule to add.

        Raises
        ------
        ValueError
            If a rule by this name already exists
        RuntimeError
            If the rule uses a remote for which no IDL file is available
            in the ts_idl package.
        RuntimeEror:
            If the rule references a topic that does not exist.
        """
        if rule.name in self.rules:
            raise ValueError(f"A rule named {rule.name} already exists")
        rule.alarm.callback = self.alarm_callback
        # create remotes and add callbacks
        for remote_info in rule.remote_info_list:
            remote = self.remotes.get(remote_info.key, None)
            if remote is None:
                remote = salobj.Remote(domain=self.domain,
                                       name=remote_info.name, index=remote_info.index,
                                       readonly=True, include=[], start=False)
                self.remotes[remote_info.key] = remote
            wrapper = base.RemoteWrapper(remote=remote, topic_names=remote_info.topic_names)
            setattr(rule, wrapper.attr_name, wrapper)
            for topic_name in remote_info.callback_names:
                topic = getattr(remote, topic_name, None)
                if topic is None:
                    raise RuntimeError(f"Bug: could not get topic {topic_name} from remote "
                                       "after constructing the remote wrapper")
                if topic.callback is None:
                    topic.callback = base.TopicCallback(topic=topic, rule=rule, model=self)
                else:
                    topic.callback.add_rule(rule)
        # add the rule
        self.rules[rule.name] = rule

    def get_rules(self, name_regex):
        """Get all rules whose name matches the specified regular expression.

        Parameters
        ----------
        name_regex : `str`
            Rule/alarm name.
            If a regular expression then return all matching rules.

        Returns
        -------
        rules : `generator`
            An iterator over rules.
        """
        compiled_re = re.compile(name_regex)
        return (rule for name, rule in self.rules.items() if compiled_re.match(name) is not None)

    def mute_alarm(self, name, duration, severity, user):
        """Mute one or more alarms for a specified duration.

        Parameters
        ----------
        name : `str`
            Regular expression for alarm name(s) to mute.
        duration : `float`
            How long to mute the alarm (sec)
        severity : `lsst.ts.idl.enums.Watcher.AlarmSeverity` or `int`
            Severity to mute; used to set the ``mutedSeverity`` field of
            the ``alarm`` event.
        user : `str`
            Name of user; used to set acknowledged_by.
        """
        for rule in self.get_rules(name):
            rule.alarm.mute(duration=duration, severity=severity, user=user)

    def unmute_alarm(self, name):
        """Unmute one or more alarms.

        Parameters
        ----------
        name : `str`
            Regular expression for alarm name(s) to unmute.
        """
        for rule in self.get_rules(name):
            rule.alarm.unmute()

    async def __aenter__(self):
        await self.start_task
        return self

    async def __aexit__(self, type, value, traceback):
        await self.close()
