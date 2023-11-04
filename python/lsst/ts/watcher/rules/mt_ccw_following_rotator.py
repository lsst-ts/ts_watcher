from __future__ import annotations

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

__all__ = ["MTCCWFollowingRotator"]

import typing

from lsst.ts import watcher
from lsst.ts.idl.enums.Watcher import AlarmSeverity

if typing.TYPE_CHECKING:
    from lsst.ts.salobj import BaseMsgType


class MTCCWFollowingRotator(watcher.BaseRule):
    """Check that the MT camera cable wrap is following the camera rotator.

    Set alarm severity WARNING if the MTMount CSC reports that it is not
    following the camera rotator, NONE otherwise.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Ignored, because this rule has no configuration.
    log : `logging.Logger`, optional
        Parent logger.

    Notes
    -----
    The alarm name is "MTCCWFollowingRotator".
    """

    def __init__(self, config, log=None):
        remote_info = watcher.RemoteInfo(
            name="MTMount",
            index=0,
            callback_names=["evt_cameraCableWrapFollowing"],
            poll_names=[],
        )
        super().__init__(
            config=config,
            name="MTCCWFollowingRotator",
            remote_info_list=[remote_info],
            log=log,
        )

    @classmethod
    def get_schema(cls):
        return None

    def compute_alarm_severity(
        self, data: BaseMsgType, **kwargs: typing.Any
    ) -> watcher.AlarmSeverityReasonType:
        enabled = data.enabled
        if enabled:
            return watcher.NoneNoReason
        return (
            AlarmSeverity.WARNING,
            "MT camera cable wrap is not following the rotator",
        )
