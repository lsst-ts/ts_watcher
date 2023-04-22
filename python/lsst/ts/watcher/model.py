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

__all__ = ["get_rule_class", "Model"]

import asyncio
import fnmatch
import inspect
import re

from lsst.ts import salobj, utils

from . import rules
from .filtered_topic_wrapper import FilteredTopicWrapper, get_filtered_topic_wrapper_key
from .remote_wrapper import RemoteWrapper
from .topic_callback import TopicCallback, get_topic_key


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
    alarm_callback : callable, optional
        Coroutine (async function) to call whenever an alarm changes state,
        or None if no callback wanted.
        The coroutine receives one argument: this alarm.

    Raises
    ------
    TypeError
        If alarm_callback is not None and not a coroutine.
    """

    def __init__(self, domain, config, alarm_callback=None):
        if alarm_callback is not None and not inspect.iscoroutinefunction(
            alarm_callback
        ):
            raise TypeError(f"alarm_callback={alarm_callback} must be async")

        self.domain = domain
        self.alarm_callback = alarm_callback

        self._enabled = False
        self.enable_task = utils.make_done_future()

        # Dict of (sal_component_name, sal_index): lsst.ts.salobj.Remote
        self.remotes = dict()

        # Dict of topic_key: FilteredTopicWrapper
        self.filtered_topic_wrappers = dict()

        # Dict of rule_name: Rule
        self.rules = dict()

        # Convert disabled_sal_components
        # from a list of names in the form ``name`` or ``name:index``
        # to frozenset of keys in the form ``(name, index)``.
        config.disabled_sal_components = frozenset(
            salobj.name_to_name_index(name) for name in config.disabled_sal_components
        )
        self.config = config

        # Make the rules.
        for ruledata in self.config.rules:
            ruleclassname = ruledata["classname"]
            ruleclass = get_rule_class(ruleclassname)
            for i, ruleconfig_dict in enumerate(ruledata["configs"]):
                try:
                    ruleconfig = ruleclass.make_config(**ruleconfig_dict)
                except Exception as e:
                    raise ValueError(
                        f"Config {i+1} for rule class {ruleclassname} not valid: "
                        f"config={ruleconfig_dict}"
                    ) from e
                rule = ruleclass(config=ruleconfig)
                if rule.is_usable(
                    disabled_sal_components=config.disabled_sal_components
                ):
                    self.add_rule(rule)

        # Accumulate a list of topics that have callback functions.
        self._topics_with_callbacks = list()
        for remote in self.remotes.values():
            for name in dir(remote):
                if name[0:4] in ("evt_", "tel_"):
                    topic = getattr(remote, name)
                    if topic.callback is not None:
                        self._topics_with_callbacks.append(topic)

        # Set escalation information in the alarms.
        remaining_names = set(self.rules)
        for escalation_item in config.escalation:
            for name_glob in escalation_item["alarms"]:
                name_regex = fnmatch.translate(name_glob)
                compiled_name_regex = re.compile(name_regex, re.IGNORECASE)
                matched_names = [
                    name for name in remaining_names if compiled_name_regex.match(name)
                ]
                remaining_names = remaining_names.difference(matched_names)
                for name in matched_names:
                    alarm = self.rules[name].alarm
                    alarm.configure_escalation(
                        escalation_responder=escalation_item["responder"],
                        escalation_delay=escalation_item["delay"],
                    )

        # Finish setup
        for rule in self.rules.values():
            rule.setup(self)

        self.start_task = asyncio.ensure_future(self.start())

    @property
    def enabled(self):
        """Get or set the enabled state of the Watcher model."""
        return self._enabled

    def enable(self):
        """Enable the model. A no-op if already enabled."""
        if self._enabled:
            return
        self._enabled = True
        callback_coros = []
        for rule in self.rules.values():
            rule.alarm.reset()
            rule.start()
        for topic in self._topics_with_callbacks:
            data = topic.get()
            if data is not None:
                callback_coros.append(topic._run_callback(data))
        self.enable_task = asyncio.ensure_future(asyncio.gather(*callback_coros))

    def disable(self):
        """Disable the model. A no-op if already disabled."""
        if not self._enabled:
            return
        self._enabled = False
        self.enable_task.cancel()

    async def start(self):
        """Start all remotes."""
        await asyncio.gather(*[remote.start() for remote in self.remotes.values()])

    async def close(self):
        """Stop rules and close remotes."""
        for rule in self.rules.values():
            rule.alarm.close()
        self.disable()
        await asyncio.gather(*[remote.close() for remote in self.remotes.values()])

    async def acknowledge_alarm(self, name, severity, user):
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
            await rule.alarm.acknowledge(severity=severity, user=user)

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
        rule.alarm.configure_basics(
            callback=self.alarm_callback,
            auto_acknowledge_delay=self.config.auto_acknowledge_delay,
            auto_unacknowledge_delay=self.config.auto_unacknowledge_delay,
        )
        # Create remotes and add callbacks.
        for remote_info in rule.remote_info_list:
            remote = self.remotes.get(remote_info.key, None)
            if remote is None:
                remote = salobj.Remote(
                    domain=self.domain,
                    name=remote_info.name,
                    index=remote_info.index,
                    readonly=True,
                    include=[],
                    start=False,
                )
                self.remotes[remote_info.key] = remote
            wrapper = RemoteWrapper(remote=remote, topic_names=remote_info.topic_names)
            setattr(rule, wrapper.attr_name, wrapper)
            for topic_name in remote_info.callback_names:
                topic = getattr(remote, topic_name, None)
                if topic is None:
                    raise RuntimeError(
                        f"Bug: could not get topic {topic_name} from remote "
                        "after constructing the remote wrapper"
                    )
                if topic.callback is None:
                    topic.callback = TopicCallback(topic=topic, rule=rule, model=self)
                else:
                    topic.callback.add_rule(rule)
        # Add the rule.
        self.rules[rule.name] = rule

    def get_filtered_topic_wrapper(self, topic, filter_field):
        """Get an existing `TopicWrapper`.

        Parameters
        ----------
        topic : `lsst.ts.salobj.ReadTopic`
            Topic to read.
        filter_field : `str`
            Field to filter on. The field must be a scalar.
            It should also have a smallish number of expected values,
            in order to avoid caching too much data.

        Raises
        ------
        KeyError
            If the wrapper is not in the registry.
        """
        key = get_filtered_topic_wrapper_key(
            topic_key=get_topic_key(topic), filter_field=filter_field
        )
        return self.filtered_topic_wrappers[key]

    def get_rules(self, name_regex):
        """Get all rules whose name matches the specified regular expression.

        Parameters
        ----------
        name_regex : `str`
            Regular expression for alarm name(s) to return.

        Returns
        -------
        rules : `generator`
            An iterator over rules.
        """
        compiled_re = re.compile(name_regex)
        return (
            rule
            for name, rule in self.rules.items()
            if compiled_re.match(name) is not None
        )

    def make_filtered_topic_wrapper(self, topic, filter_field):
        """Make a FilteredTopicWrapper, or return an existing one, if found.

        Call this, instead of constructing a `FilteredTopicWrapper` directly.
        That makes sure cached value is returned, if it exists (avoiding
        an exception in the class constructor).

        Parameters
        ----------
        topic : `lsst.ts.salobj.ReadTopic`
            Topic to read.
        filter_field : `str`
            Field to filter on. The field must be a scalar.
            It should also have a smallish number of expected values,
            in order to avoid caching too much data.

        Notes
        -----
        Watcher rules typically do not use `FilteredTopicWrapper` directly.
        Instead they use subclasses of `BaseFilteredFieldWrapper`.
        Each filtered field wrapper creates a `FilteredTopicWrapper`
        for internal use.
        """
        key = get_filtered_topic_wrapper_key(
            topic_key=get_topic_key(topic), filter_field=filter_field
        )
        wrapper = self.filtered_topic_wrappers.get(key, None)
        if wrapper is None:
            wrapper = FilteredTopicWrapper(
                model=self, topic=topic, filter_field=filter_field
            )
        return wrapper

    async def mute_alarm(self, name, duration, severity, user):
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
            await rule.alarm.mute(duration=duration, severity=severity, user=user)

    async def unacknowledge_alarm(self, name):
        """Unacknowledge one or more alarms.

        Parameters
        ----------
        name : `str`
            Regular expression for alarm name(s) to unacknowledge.
        """
        for rule in self.get_rules(name):
            await rule.alarm.unacknowledge()

    async def unmute_alarm(self, name):
        """Unmute one or more alarms.

        Parameters
        ----------
        name : `str`
            Regular expression for alarm name(s) to unmute.
        """
        for rule in self.get_rules(name):
            await rule.alarm.unmute()

    async def __aenter__(self):
        await self.start_task
        return self

    async def __aexit__(self, type, value, traceback):
        await self.close()
