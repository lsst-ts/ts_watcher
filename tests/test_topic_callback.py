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
from lsst.ts import utils
from lsst.ts import watcher

STD_TIMEOUT = 5  # Max time to send/receive a topic (seconds)

index_gen = utils.index_generator()


class BadEnabledRule(watcher.rules.Enabled):
    """A variant of the Enabled rule that raises in `__call__`.

    Do not try to use the alarm's severity_queue attribute, because
    the exception in `__call__` prevents severities from being added to it.

    Attributes
    ----------
    num_callbacks : `int`
        The number of times the rule has been called.
    num_callbacks_queue : `asyncio.Queue`
        A queue of the number of callbacks.
    """

    def __init__(self, **kwargs):
        self.num_callbacks = 0
        self.num_callbacks_queue = asyncio.Queue()
        super().__init__(**kwargs)
        self.alarm.name = "Bad" + self.alarm.name

    def __call__(self, topic_callback):
        self.num_callbacks += 1
        self.num_callbacks_queue.put_nowait(self.num_callbacks)
        raise RuntimeError("BadEnabledRule.__call__ intentionally raises")

    async def assert_next_num_callbacks(
        self, expected_num_callbacks, timeout=STD_TIMEOUT
    ):
        """Wait for the functor to be called and check num_callbacks."""
        num_callbacks = await asyncio.wait_for(
            self.num_callbacks_queue.get(), timeout=timeout
        )
        assert num_callbacks == expected_num_callbacks
        assert self.num_callbacks_queue.empty()


class BadTopicWrapper(watcher.FilteredTopicWrapper):
    """A variant of FilteredTopicWrapper that raises in the callback.

    Attributes
    ----------
    num_callbacks : `int`
        The number of times the wrapper has been called.
    num_callbacks_queue : `asyncio.Queue`
        A queue of the number of callbacks.
    """

    def __init__(self, **kwargs):
        self.num_callbacks = 0
        self.num_callbacks_queue = asyncio.Queue()
        super().__init__(**kwargs)

    def __call__(self, topic_callback):
        self.num_callbacks += 1
        self.num_callbacks_queue.put_nowait(self.num_callbacks)
        raise RuntimeError("BadTopicWrapper.__call__ intentionally raises")

    async def assert_next_num_callbacks(
        self, expected_num_callbacks, timeout=STD_TIMEOUT
    ):
        """Wait for the functor to be called and check num_callbacks."""
        num_callbacks = await asyncio.wait_for(
            self.num_callbacks_queue.get(), timeout=timeout
        )
        assert num_callbacks == expected_num_callbacks
        assert self.num_callbacks_queue.empty()


class TopicCallbackTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()
        self.index = next(index_gen)

    def make_enabled_rule(self):
        """Make an Enabled rule and init the alarm's severity queue.

        Returns
        -------
        rule : `rules.EnabledRule`
            The constructed EnabledRule
        """
        config = types.SimpleNamespace(name=f"Test:{self.index}")
        rule = watcher.rules.Enabled(config=config)
        rule.alarm.init_severity_queue()
        return rule

    async def test_basics(self):
        model = watcher.MockModel(enabled=True)

        rule = self.make_enabled_rule()

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

            await controller.evt_summaryState.set_write(
                summaryState=salobj.State.DISABLED, force_output=True
            )
            await rule.alarm.assert_next_severity(AlarmSeverity.WARNING)

    async def test_add_rule(self):
        model = watcher.MockModel(enabled=True)

        # Make the first rule one that raises when called, in order to test
        # test that TopicCallback continues to call additional rules.
        config = types.SimpleNamespace(name=f"Test:{self.index}")
        bad_rule = BadEnabledRule(config=config)
        rule2 = self.make_enabled_rule()
        rule3 = self.make_enabled_rule()

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
            topic_callback.add_rule(rule2)

            await controller.evt_summaryState.set_write(
                summaryState=salobj.State.DISABLED, force_output=True
            )
            await bad_rule.assert_next_num_callbacks(1)
            await rule2.alarm.assert_next_severity(AlarmSeverity.WARNING)
            assert rule3.alarm.severity_queue.empty()

            # Cannot add rule3 because it has the same name as rule2.
            with pytest.raises(ValueError):
                topic_callback.add_rule(rule3)

            # Modify the name of rule3 and try again. This should work.
            rule3.alarm.name = rule3.alarm.name + "modified"
            topic_callback.add_rule(rule3)
            await controller.evt_summaryState.set_write(
                summaryState=salobj.State.FAULT, force_output=True
            )
            await bad_rule.assert_next_num_callbacks(2)
            await rule2.alarm.assert_next_severity(AlarmSeverity.SERIOUS)
            await rule3.alarm.assert_next_severity(AlarmSeverity.SERIOUS)

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
                    await controller.tel_scalars.set_write(**data_dict)
                    await bad_wrapper.assert_next_num_callbacks(i + 1)
                    wrapper_data = wrapper.get_data(filter_value)
                    assert wrapper_data is not None
                    assert wrapper_data.double0 == data_dict[data_field]
