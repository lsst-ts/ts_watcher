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

from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts.watcher import base


class MTCCWFollowingRotator(base.BaseRule):
    """Check that the MT camera cable wrap is following the camera rotator.

    Set alarm severity WARNING if the MTMount CSC reports that it is not
    following the camera rotator, NONE otherwise.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Ignored, because this rule has no configuration.

    Notes
    -----
    The alarm name is "MTCCWFollowingRotator".
    """

    def __init__(self, config):
        remote_info = base.RemoteInfo(
            name="MTMount",
            index=0,
            callback_names=["evt_cameraCableWrapFollowing"],
            poll_names=[],
        )
        super().__init__(
            config=config,
            name="MTCCWFollowingRotator",
            remote_info_list=[remote_info],
        )

    @classmethod
    def get_schema(cls):
        return None

    def __call__(self, topic_callback):
        enabled = topic_callback.get().enabled
        if enabled:
            return base.NoneNoReason
        return (
            AlarmSeverity.WARNING,
            "MT camera cable wrap is not following the rotator",
        )
