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
    """A Watcher alarm.

    Parameters
    ----------
    domain : `lsst.ts.salobj.Domain`
        DDS Domain.
    config : `types.SimpleNamespace`
        Watcher configuration validated against the Watcher schema.
    """
    def __init__(self, domain, config):
        self.domain = domain
        # dict of (sal_component_name, sal_index): lsst.ts.salobj.Remote
        self.remotes = dict()
        # dict of rule_name: Rule
        self.rules = dict()
        self._enabled = False
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

    @property
    def enabled(self):
        """Get or set the enabled state of the Watcher model.

        The model should be enabled when the CSC is in the ENABLED state,
        and disabled otherwise.
        """
        return self._enabled

    @enabled.setter
    def enabled(self, enabled):
        self._enabled = bool(enabled)
        if self._enabled:
            for rule in self.rules.values():
                rule.start()
        else:
            for rule in self.rules.values():
                rule.stop()

    async def start(self):
        """Start all remotes."""
        await asyncio.gather(*[remote.start() for remote in self.remotes.values()])

    async def close(self):
        """Stop rules and close remotes.
        """
        self.enabled = False
        await asyncio.gather(*[remote.close() for remote in self.remotes.values()])

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

    def alarm_callback(self, alarm):
        pass

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, type, value, traceback):
        await self.close()
