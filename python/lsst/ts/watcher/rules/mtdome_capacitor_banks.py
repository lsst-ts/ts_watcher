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

__all__ = ["MTDomeCapacitorBanks"]

import typing

from lsst.ts import salobj
from lsst.ts.xml.enums.Watcher import AlarmSeverity

from ..base_rule import AlarmSeverityReasonType, BaseRule, NoneNoReason
from ..remote_info import RemoteInfo

REASON_DICT: dict[str, str] = {
    "doorOpen": "Open door",
    "fuseIntervention": "Broken fuse",
    "highTemperature": "High temperature",
    "lowResidualVoltage": "Low residual voltage",
    "smokeDetected": "Smoke",
}


class MTDomeCapacitorBanks(BaseRule):
    """Monitor the MTDome capacitor banks for any alarming states.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
    log : `logging.Logger`, optional
        Parent logger.
    """

    def __init__(self, config, log=None):
        remote_name = "MTDome"
        remote_index = 0
        remote_info_list = [
            RemoteInfo(
                name=remote_name,
                index=remote_index,
                callback_names=["evt_capacitorBanks"],
                poll_names=[],
            )
        ]
        super().__init__(
            config=config,
            name=f"MTDomeCapacitorBanks.{remote_name}",
            remote_info_list=remote_info_list,
            log=log,
        )

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
        severity, reason = NoneNoReason

        reason_list: list[str] = []
        for item_name in REASON_DICT:
            # For any of the attributes, value is a list of bool.
            if hasattr(data, item_name) and True in getattr(data, item_name):
                reason_list.append(f"{REASON_DICT[item_name]} detected")
        if reason_list:
            reason = ", ".join(reason_list)
            severity = AlarmSeverity.CRITICAL

        return severity, reason
