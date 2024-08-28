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

__all__ = ["MTVibrationRotator"]

import logging
import types
import typing

from lsst.ts import salobj, watcher
from lsst.ts.xml.enums.Watcher import AlarmSeverity

from ..base_rule import AlarmSeverityReasonType, NoneNoReason
from ..remote_info import RemoteInfo


class MTVibrationRotator(watcher.BaseRule):
    """Monitor the main telescope vibration event based on the rotator
    detection.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
    log : `logging.Logger` or None, optional
        Parent logger. (the default is None)
    """

    def __init__(
        self, config: types.SimpleNamespace, log: logging.Logger | None = None
    ):

        remote_name = "MTRotator"
        remote_info = RemoteInfo(
            remote_name,
            0,
            callback_names=["evt_lowFrequencyVibration"],
        )
        super().__init__(
            config,
            f"MTVibrationRotator.{remote_name}",
            [remote_info],
            log=log,
        )

    @classmethod
    def get_schema(cls):
        # No schema necessary for this rule.
        return None

    def compute_alarm_severity(
        self, data: salobj.BaseMsgType, **kwargs: dict[str, typing.Any]
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

        frequency = data.frequency

        return (
            NoneNoReason
            if (frequency == 0.0)
            else (
                AlarmSeverity.WARNING,
                f"Rotator detects the vibration of {frequency} Hz.",
            )
        )
