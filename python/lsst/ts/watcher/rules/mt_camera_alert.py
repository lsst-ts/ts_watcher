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

__all__ = ["MTCameraAlert", "CameraSeverity"]

import enum
import typing

from lsst.ts import salobj
from lsst.ts.xml.enums.Watcher import AlarmSeverity

from ..base_rule import AlarmSeverityReasonType, BaseRule, NoneNoReason
from ..remote_info import RemoteInfo


class MTCameraAlert(BaseRule):
    """Monitor the MT Camera alertRaised events.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
    rule_name : `str`
        Rule name.
    callback_names : list[`str`]
        Callback names, i.e. SAL topics to which the rule applies.
    log : `logging.Logger`, optional
        Parent logger.
    """

    def __init__(self, config, log=None):
        rule_name = "MTCameraAlert"
        remote_name = "MTCamera"
        remote_index = 0
        callback_name = "evt_alertRaised"

        remote_info_list = [
            RemoteInfo(
                name=remote_name,
                index=remote_index,
                callback_names=[callback_name],
                poll_names=[],
            )
        ]
        super().__init__(
            config=config,
            name=f"{rule_name}.{remote_name}.{callback_name}",
            remote_info_list=remote_info_list,
            log=log,
        )

    @classmethod
    def get_schema(cls):
        # No schema needed for this rule.
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
        currentSeverity = CameraSeverity(data.currentSeverity)

        if not data.isCleared:
            reason = (
                f"Event details: alertId={data.alertId}, description={data.description}, "
                f"currentSeverity={currentSeverity.name}, isCleared={data.isCleared}, "
                f"cause={data.cause}, origin={data.origin}, additionalInfo={data.additionalInfo}"
            )
            match data.currentSeverity:
                case CameraSeverity.NOMINAL:
                    severity = AlarmSeverity.WARNING
                case CameraSeverity.WARNING:
                    severity = AlarmSeverity.SERIOUS
                case CameraSeverity.ALARM:
                    severity = AlarmSeverity.CRITICAL
                case _:
                    severity, reason = NoneNoReason
        else:
            severity, reason = NoneNoReason

        return severity, reason


class CameraSeverity(enum.IntEnum):
    """Enum that represents CCCamera severity levels."""

    NOMINAL = 1
    WARNING = 2
    ALARM = 3
