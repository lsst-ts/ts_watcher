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

import asyncio
import pytest
import types
import unittest

from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts import salobj
from lsst.ts import watcher

STD_TIMEOUT = 5  # Max time to send/receive a topic (seconds)
LONG_TIMEOUT = 60  # Max Remote startup time (seconds)

index_gen = salobj.index_generator()


class BadEnabledRule(watcher.rules.Enabled):
    """A variant of the Enabled rule that raises in the callback.

    Attributes
    ----------
    num_callbacks : `int`
        The number of times the rule has been called.
    """

    def __init__(self, **kwargs):
        self.num_callbacks = 0
        super().__init__(**kwargs)
        self.alarm.name = "Bad" + self.alarm.name

    def __call__(self, topic_callback):
        self.num_callbacks += 1
        raise RuntimeError("BadEnabledRule.__call__ intentionally raises")


class BadTopicWrapper(watcher.FilteredTopicWrapper):
    """A variant of FilteredTopicWrapper that raises in the callback.

    Attributes
    ----------
    num_callbacks : `int`
        The number of times the wrapper has been called.
    """

    def __init__(self, **kwargs):
        self.num_callbacks = 0
        super().__init__(**kwargs)

    def __call__(self, topic_callback):
        self.num_callbacks += 1
        raise RuntimeError("BadTopicWrapper.__call__ intentionally raises")


class TopicCallbackTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()
        self.index = next(index_gen)

    def make_enabled_rule(self):
        """Make an Enabled rule and callback.

        Returns
        -------
        A tuple of:

        * rule: the constructed EnabledRule
        * read_severities: a list of severities read from the rule.
            This will be updated as the rule is called.
        """
        config = types.SimpleNamespace(name=f"Test:{self.index}")
        rule = watcher.rules.Enabled(config=config)

        read_severities = []

        def alarm_callback(alarm):
            nonlocal read_severities
            read_severities.append(alarm.severity)

        rule.alarm.callback = alarm_callback

        return rule, read_severities

    async def test_basics(self):
        model = watcher.MockModel(enabled=True)

        rule, read_severities = self.make_enabled_rule()

        async with salobj.Controller(
            name="Test", index=self.index
        ) as controller, salobj.Remote(
            domain=controller.domain,
            name="Test",
            index=self.index,
            readonly=True,
            include=["summaryState"],
        ) as remote:
            topic_callback = watcher.TopicCallback(
                topic=remote.evt_summaryState, rule=rule, model=model
            )
            assert topic_callback.attr_name == "evt_summaryState"
            assert topic_callback.remote_name == "Test"
            assert topic_callback.remote_index == self.index
            assert topic_callback.get() is None
            assert read_severities == []

            controller.evt_summaryState.set_put(
                summaryState=salobj.State.DISABLED, force_output=True
            )
            await asyncio.sleep(0.001)
            assert read_severities == [AlarmSeverity.WARNING]

    async def test_add_rule(self):
        model = watcher.MockModel(enabled=True)

        # Make the first rule one that raises when called, in order to test
        # test that TopicCallback continues to call additional rules.
        config = types.SimpleNamespace(name=f"Test:{self.index}")
        bad_rule = BadEnabledRule(config=config)
        rule, read_severities = self.make_enabled_rule()
        rule2, read_severities2 = self.make_enabled_rule()

        async with salobj.Controller(
            name="Test", index=self.index
        ) as controller, salobj.Remote(
            domain=controller.domain,
            name="Test",
            index=self.index,
            readonly=True,
            include=["summaryState"],
        ) as remote:
            topic_callback = watcher.TopicCallback(
                topic=remote.evt_summaryState, rule=bad_rule, model=model
            )
            topic_callback.add_rule(rule)

            assert read_severities == []
            assert read_severities2 == []

            controller.evt_summaryState.set_put(
                summaryState=salobj.State.DISABLED, force_output=True
            )
            await asyncio.sleep(0.001)
            assert bad_rule.num_callbacks == 1
            assert read_severities == [AlarmSeverity.WARNING]
            # rule2 has not been added so read_severities2 should be empty
            assert read_severities2 == []

            # cannot add a rule with the same name as an existing rule
            with pytest.raises(ValueError):
                topic_callback.add_rule(rule2)

            # modify the rule and try again
            rule2.alarm.name = rule2.alarm.name + "modified"
            topic_callback.add_rule(rule2)
            controller.evt_summaryState.set_put(
                summaryState=salobj.State.FAULT, force_output=True
            )
            await asyncio.sleep(0.001)
            assert bad_rule.num_callbacks == 2
            assert read_severities == [AlarmSeverity.WARNING, AlarmSeverity.SERIOUS]
            assert read_severities2 == [AlarmSeverity.SERIOUS]

    async def test_add_wrapper(self):
        filter_field = "int0"
        other_filter_field = "short0"
        data_field = "double0"

        async with salobj.Controller(
            name="Test", index=self.index
        ) as controller, salobj.Remote(
            domain=controller.domain,
            name="Test",
            index=self.index,
            readonly=True,
            include=["summaryState"],
        ) as remote:

            model = watcher.MockModel(enabled=True)

            async with salobj.Controller(
                name="Test", index=self.index
            ) as controller, salobj.Remote(
                domain=controller.domain,
                name="Test",
                index=self.index,
                readonly=True,
                include=["scalars"],
            ) as remote:
                topic_callback = watcher.TopicCallback(
                    topic=remote.tel_scalars, rule=None, model=model
                )
                assert remote.tel_scalars.callback is topic_callback

                # Make the first wrapper one that raises when called,
                # in order to test that TopicCallback continues to call
                # additional wrappers. Use a different filter_field because
                # we can only have one wrapper per (topic, filter_field)
                bad_wrapper = BadTopicWrapper(
                    model=model,
                    topic=remote.tel_scalars,
                    filter_field=other_filter_field,
                )
                good_wrapper = model.make_filtered_topic_wrapper(
                    topic=remote.tel_scalars, filter_field=filter_field
                )

                # Test the filtered topic wrapper cache
                assert len(model.filtered_topic_wrappers) == 2
                topic_key = watcher.get_topic_key(remote.tel_scalars)
                for wrapper in (bad_wrapper, good_wrapper):
                    key = watcher.get_filtered_topic_wrapper_key(
                        topic_key=topic_key, filter_field=wrapper.filter_field
                    )
                    assert model.filtered_topic_wrappers[key] is wrapper

                # Test reading filtered data
                data_dict_list = [
                    {filter_field: 1, data_field: 3.5},
                    {filter_field: 2, data_field: 2.4},
                    {filter_field: 1, data_field: -13.1},
                    {filter_field: 2, data_field: -13.1},
                ]
                for i, data_dict in enumerate(data_dict_list):
                    filter_value = data_dict[filter_field]
                    controller.tel_scalars.set_put(**data_dict)
                    await asyncio.sleep(0.001)
                    assert bad_wrapper.num_callbacks == i + 1
                    wrapper_data = wrapper.get_data(filter_value)
                    assert wrapper_data is not None
                    assert wrapper_data.double0 == data_dict[data_field]
