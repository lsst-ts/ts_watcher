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

__all__ = ["ATeStop"]

import typing

from lsst.ts import salobj
from lsst.ts.xml.enums.Watcher import AlarmSeverity
from lsst.ts.xml.sal_enums import State

from ..base_rule import AlarmSeverityReasonType, BaseRule, NoneNoReason
from ..remote_info import RemoteInfo


class ATeStop(BaseRule):
    """Monitor the AT eStop.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
    log : `logging.Logger`, optional
        Parent logger.
    """

    def __init__(self, config, log=None):
        remote_name = "ATPneumatics"
        remote_index = 0
        remote_info_list = [
            RemoteInfo(
                name=remote_name,
                index=remote_index,
                callback_names=["evt_summaryState", "evt_eStop"],
                poll_names=[],
            )
        ]
        rule_name = "eStop"
        super().__init__(
            config=config,
            name=f"{rule_name}.{remote_name}",
            remote_info_list=remote_info_list,
            log=log,
        )

        self.may_raise = False
        self.estop_triggered = False

    @classmethod
    def get_schema(cls):
        # No schema necessary for this rule.
        return None

    def compute_alarm_severity(
        self, data: salobj.BaseMsgType, **kwargs: typing.Any
    ) -> AlarmSeverityReasonType:
        """Compute and set alarm severity and reason.

        Parameters
        ----------
        data : `salobj.BaseMsgType`
              Message from the topic described by topic_callback.
        **kwargs : `dict` [`str`, `typing.Any`]
            Keyword arguments. If triggered by `TopicCallback` calling
            `update_alarm_severity`, the arguments will be as follows:

            * topic_callback : `TopicCallback`
              Topic callback wrapper.

        Returns
        -------
        None, if no change or unknown, or a tuple of two values:

        severity: `lsst.ts.xml.enums.Watcher.AlarmSeverity`
            The new alarm severity.
        reason : `str`
            Detailed reason for the severity, e.g. a string describing
            what value is out of range, and what the range is.
            If ``severity`` is ``NONE`` then this value is ignored (but still
            required) and the old reason is retained until the alarm is reset
            to ``nominal`` state.

        Notes
        -----
        You may return `NoneNoReason` if the alarm state is ``NONE``.
        """
        severity_and_reason = NoneNoReason

        if hasattr(data, "triggered"):
            self.estop_triggered = data.triggered
        if hasattr(data, "summaryState"):
            self.may_raise = State(data.summaryState) == State.ENABLED
        self.log.debug(f"{self.estop_triggered=}, {self.may_raise=}")

        if self.may_raise and self.estop_triggered:
            severity_and_reason = (
                AlarmSeverity.CRITICAL,
                "ATPneumatics ENABLED and eStop triggered.",
            )

        return severity_and_reason
