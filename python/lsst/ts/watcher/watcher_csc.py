# This file is part of ts_watcher.
#
# Developed for the Vera C. Rubin Observatory Telescope and Site Systems.
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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

__all__ = ["WatcherCsc", "run_watcher"]

import asyncio
import copy
import logging
import os
import re
import types

import aiohttp
import yaml

from lsst.ts import salobj, utils
from lsst.ts.salobj.base import get_user_host
from lsst.ts.xml.enums.AlarmRule import AlarmRuleState
from lsst.ts.xml.enums.Watcher import AlarmSeverity

from . import __version__
from .config_schema import CONFIG_SCHEMA
from .watcher_utils import AlarmInfo, AlarmRuleInfo

# URL suffix for the SquadCast Incident Webhook API
INCIDENT_WEBHOOK_URL_SUFFIX = "/v2/incidents/api/"

# Standard timeout applied to some regular CSC
# operations (in seconds).
STD_TIMEOUT = 120

# The script name.
SCRIPT_NAME = "run_alarm_rule_runner"

# Process communicate timeout [sec].
PROCESS_COMM_TIMEOUT = 20

# Dict of alarm severity levels and their corresponding logging levels.
alarm_severity_level = {
    AlarmSeverity.NONE: logging.DEBUG,
    AlarmSeverity.SERIOUS: logging.INFO,
    AlarmSeverity.WARNING: logging.WARNING,
    AlarmSeverity.CRITICAL: logging.CRITICAL,
}


class WatcherCsc(salobj.ConfigurableCsc):
    """The Watcher CSC.

    Parameters
    ----------
    config_dir : `str`, optional
        Directory of configuration files, or None for the standard
        configuration directory (obtained from `get_default_config_dir`).
        This is provided for unit testing.
    initial_state : `salobj.State` or `int`, optional
        The initial state of the CSC. This is provided for unit testing,
        as real CSCs should start up in `lsst.ts.salobj.StateSTANDBY`,
        the default.
    override : `str`, optional
        Configuration override file to apply if ``initial_state`` is
        `State.DISABLED` or `State.ENABLED`.

    Raises
    ------
    salobj.ExpectedError
        If initial_state is invalid.
    """

    valid_simulation_modes = [0]
    enable_cmdline_state = True
    require_settings = True
    version = __version__

    def __init__(self, config_dir=None, initial_state=salobj.State.STANDBY, override=""):
        self.http_client = aiohttp.ClientSession()

        super().__init__(
            "Watcher",
            index=0,
            config_schema=CONFIG_SCHEMA,
            config_dir=config_dir,
            initial_state=initial_state,
            override=override,
        )
        self.escalation_endpoint_url = ""
        self.config: types.SimpleNamespace | None = None

        # Dict of AlarmRule index and info for that AlarmRule.
        self.alarm_rules_info: dict[int, AlarmRuleInfo] = {}

        # List of received alarms.
        self.alarms_info: dict[str, AlarmInfo] = {}

        # Lock to protect access to self.alarms.
        self.alarms_lock = asyncio.Lock()

        # Remote to communicate with AlarmRuleRunner instances.
        self.log.debug("Creating AlarmRuleRemote.")
        self.alarm_rule_remote = salobj.Remote(domain=self.domain, name="AlarmRule")
        self.alarm_rule_remote.evt_description.callback = self.evt_description_callback
        self.alarm_rule_remote.evt_state.callback = self.evt_state_callback
        self.alarm_rule_remote.evt_alarm.callback = self.evt_alarm_callback
        self.alarm_rule_remote.evt_logLevel.callback = self.evt_logLevel_callback
        self.alarm_rule_remote.evt_logMessage.callback = self.evt_logMessage_callback

    @staticmethod
    def get_config_pkg():
        return "ts_config_ocs"

    async def close_tasks(self):
        await super().close_tasks()

        # Command all remotes to stop and stop the remotes themselves as well
        # as the subprocesses.
        for index in self.alarm_rules_info:
            alarm_rule_info = self.alarm_rules_info[index]

            self.log.debug(f"Stopping AlarmRule:{index} for rule {alarm_rule_info.classname}.")
            await self.alarm_rule_remote.cmd_stop.set_start(salIndex=index, timeout=STD_TIMEOUT)
            self.log.debug(f"AlarmRule:{index} is stopped.")

            process = alarm_rule_info.process
            self.log.debug(
                f"Waiting for alarm rule process {process.pid} for rule {alarm_rule_info.classname} to exit."
            )
            while process.returncode is None:
                await asyncio.sleep(0.1)
            self.log.debug(f"Alarm rule process {process.pid} exited with code {process.returncode}.")

        self.alarm_rules_info = {}
        self.alarms_info = {}

        await self.http_client.close()
        # aiohttp.ClientSession needs a bit more time to fully close.
        await asyncio.sleep(0.1)

    async def begin_start(self, data):
        await self.cmd_start.ack_in_progress(
            data=data,
            timeout=STD_TIMEOUT,
        )
        await super().begin_start(data)

        for index in self.alarm_rules_info:
            self.log.debug(f"Running AlarmRule:{index}.")
            await self.alarm_rule_remote.cmd_run.set_start(salIndex=index, timeout=STD_TIMEOUT)
            self.log.debug(f"AlarmRule:{index} is running.")

    async def begin_disable(self, data) -> None:
        if self.summary_state == salobj.State.ENABLED:
            await self.close_tasks()

    async def end_enable(self, data):
        await super().end_enable(data)
        await self.output_alarms()

    async def configure(self, config: types.SimpleNamespace):
        self.config = config

        if config.escalation_url:
            try:
                escalation_key = os.environ["ESCALATION_KEY"]
            except KeyError:
                raise RuntimeError("env variable ESCALATION_KEY must be set if config.escalation_url is set")
            self.escalation_endpoint_url = (
                config.escalation_url + INCIDENT_WEBHOOK_URL_SUFFIX + escalation_key
            )
            config.escalation_url = self.escalation_endpoint_url

        for index, rule in enumerate(config.rules, start=1):
            alarm_rule_config = copy.deepcopy(config)
            alarm_rule_config.rules = [rule]
            alarm_rule_config_str = yaml.dump(vars(alarm_rule_config))

            self.log.debug(f"Starting subprocess for AlarmRuleRunner:{index} for rule {rule['classname']}.")
            process = await asyncio.create_subprocess_exec(
                SCRIPT_NAME, rule["classname"], str(index), stdin=asyncio.subprocess.PIPE
            )

            self.alarm_rules_info[index] = AlarmRuleInfo(
                classname=rule["classname"],
                config=alarm_rule_config,
                process=process,
                rule_names=[],
            )

            self.log.debug(f"Waiting for AlarmRule:{index} heartbeat for rule {rule['classname']}.")
            data = await self.alarm_rule_remote.evt_heartbeat.next(flush=True, timeout=STD_TIMEOUT)
            while data.salIndex != index:
                data = await self.alarm_rule_remote.evt_heartbeat.next(flush=True, timeout=STD_TIMEOUT)
            self.log.debug(f"AlarmRule:{index} heartbeat received.")

            self.log.debug(f"Configuring AlarmRule:{index} for rule {rule['classname']}.")
            await self.alarm_rule_remote.cmd_configure.set_start(
                salIndex=index, config=alarm_rule_config_str, timeout=STD_TIMEOUT
            )
            self.log.debug(f"Configured AlarmRule:{index}.")

    async def output_alarm(self, alarm_info, force_output=True):
        """Output the alarm event for one alarm_info instance."""
        if self.summary_state != salobj.State.ENABLED:
            return

        await self.evt_alarm.set_write(
            name=alarm_info.name,
            severity=alarm_info.severity,
            reason=alarm_info.reason,
            maxSeverity=alarm_info.max_severity,
            acknowledged=alarm_info.acknowledged,
            acknowledgedBy=alarm_info.acknowledged_by,
            mutedSeverity=alarm_info.muted_severity,
            mutedBy=alarm_info.muted_by,
            escalateTo=alarm_info.escalate_to,
            escalatedId=alarm_info.escalated_id,
            timestampSeverityOldest=alarm_info.timestamp_severity_oldest,
            timestampMaxSeverity=alarm_info.timestamp_max_severity,
            timestampAcknowledged=alarm_info.timestamp_acknowledged,
            timestampAutoAcknowledge=alarm_info.timestamp_auto_acknowledge,
            timestampAutoUnacknowledge=alarm_info.timestamp_auto_unacknowledge,
            timestampEscalate=alarm_info.timestamp_escalate,
            timestampUnmute=alarm_info.timestamp_unmute,
            force_output=force_output,
        )

    async def output_alarms(self):
        """Output the alarm events for all alarms."""
        async with self.alarms_lock:
            for alarm_name in self.alarms_info:
                alarm_info = self.alarms_info[alarm_name]
                self.log.debug(f"Outputting alarm {alarm_info.name}")
                await self.output_alarm(alarm_info)
                await asyncio.sleep(0.001)

    async def find_remotes_for_rule_regex(self, name_regex):
        """Get all remotes whose alarm classnames match the specified regular
        expression.

        Parameters
        ----------
        name_regex : `str`
            Regular expression for alarm classname(s) to match.

        Returns
        -------
        remotes : `list`[`salobj.Remote`]
            A list of remotes.
        """
        compiled_re = re.compile(name_regex)
        indices: set[int] = set()
        for index in self.alarm_rules_info:
            alarm_rule_info = self.alarm_rules_info[index]
            for rule in alarm_rule_info.rule_names:
                if compiled_re.match(rule):
                    indices.add(index)
        return indices

    async def do_acknowledge(self, data):
        self.assert_enabled()
        indices = await self.find_remotes_for_rule_regex(data.name)
        for index in indices:
            await self.alarm_rule_remote.cmd_acknowledge.set_start(
                salIndex=index,
                alarmName=data.name,
                severity=data.severity,
                acknowledgedBy=data.acknowledgedBy,
            )

    async def do_mute(self, data):
        """Mute one or more alarms."""
        self.assert_enabled()
        indices = await self.find_remotes_for_rule_regex(data.name)
        for index in indices:
            await self.alarm_rule_remote.cmd_mute.set_start(
                salIndex=index,
                alarmName=data.name,
                muteDuration=data.duration,
                severity=data.severity,
                mutedBy=data.mutedBy,
            )

    async def do_showAlarms(self, data):
        """Show all alarms."""
        self.assert_enabled()
        await self.output_alarms()

    async def do_unacknowledge(self, data):
        """Unacknowledge one or more alarms."""
        self.assert_enabled()
        indices = await self.find_remotes_for_rule_regex(data.name)
        for index in indices:
            await self.alarm_rule_remote.cmd_unacknowledge.set_start(salIndex=index, alarmName=data.name)

    async def do_unmute(self, data):
        """Unmute one or more alarms."""
        self.assert_enabled()
        indices = await self.find_remotes_for_rule_regex(data.name)
        for index in indices:
            await self.alarm_rule_remote.cmd_unmute.set_start(salIndex=index, alarmName=data.name)

    async def do_setLogLevel(self, data) -> None:
        """Set logging level.

        Also set the logging level for all alarm rules.

        Parameters
        ----------
        data : ``cmd_setLogLevel.DataType``
            Logging level.
        """
        await super().do_setLogLevel(data)

        for index in self.alarm_rules_info:
            await self.alarm_rule_remote.cmd_setLogLevel.set_start(salIndex=index, level=data.level)

        self.log.debug(f"Set log level for all alarm rules to {data.level}.")

    async def make_log_entry_for_alarm(self, log_server_url, alarm):
        """Post a message to the narrative log entry in response to alarm.

        Parameters
        ----------
        log_server_url : `str`
            URL of the narrativelog service.
        alarm : `AlarmInfo`
            The alarm to make the log entry for.

        Returns
        -------
        response : `dict`
            JSON response from Post.
        """
        now = utils.astropy_time_from_tai_unix(utils.current_tai()).datetime.isoformat()
        # Required? fields in payload:
        #   message_text, level, user_id, user_agent, is_human
        message = f"alarm:{alarm.name} severity={alarm.severity} {alarm.reason}"
        payload = {
            "message_text": message,
            "level": alarm_severity_level[alarm.severity],
            "user_id": get_user_host(),
            "user_agent": "Watcher",
            "is_human": False,
            "tags": ["watcher", "alarm", "make_log_entry"],
            "date_begin": now,
            "date_end": now,
        }

        url = f"{log_server_url}/messages"

        # AIOHTTP docs say don't create session per request. We do so anyhow.
        # By not specifying a timeout, we accept the default value of
        # 5 minutes (according to the doc)for the whole
        # operation (connect, write, response).
        async with aiohttp.ClientSession(raise_for_status=True) as session:
            async with session.post(url=url, json=payload) as response:
                response: dict = await response.json()
                self.log.debug(f"Response (json) from Post: {response=}")
        return response

    async def make_log_entry(self, log_server_url, name_regex):
        """MakeLogEntry for alarm.

        Parameters
        ----------
        log_server_url : `str`
            URL of the narrativelog service.
        name_regex : `str`
            Regular expression for alarm name(s) to post to narrative log.
        """
        compiled_re = re.compile(name_regex)
        for alarm_name in self.alarms_info:
            if not compiled_re.match(alarm_name):
                continue
            alarm = self.alarms_info[alarm_name]
            await self.make_log_entry_for_alarm(log_server_url, alarm)

    async def do_makeLogEntry(self, data):
        """Make log entry for alarms."""
        self.assert_enabled()
        log_server_url = self.config.narrative_server_url
        await self.make_log_entry(log_server_url, data.name)

    async def evt_description_callback(self, data):
        """Handle description event from alarm subprocesses."""
        self.log.debug(f"Received description event for {data.salIndex=} with {data=}")
        if data.salIndex in self.alarm_rules_info:
            alarm_rule_info = self.alarm_rules_info[data.salIndex]
            alarm_rule_info.rule_names = [f"{data.alarmName}.{remote}" for remote in data.remotes.split(",")]
            self.log.debug(
                f"AlarmRule:{data.salIndex} for {data.alarmName} has rules {alarm_rule_info.rule_names}."
            )
        else:
            self.log.warning(f"Received description event for unknown AlarmRule:{data.salIndex}.")

    async def evt_state_callback(self, data):
        """Handle state event from alarm subprocesses."""
        self.log.info(
            f"Received state event for {data.salIndex=} with state {AlarmRuleState(data.state).name}."
        )

    async def evt_alarm_callback(self, data):
        """Handle alarm event from alarm subprocesses."""
        self.log.debug(f"Received alarm event for {data.salIndex=} with {data=}")

        async with self.alarms_lock:
            if data.alarmName not in self.alarms_info:
                alarm_info = AlarmInfo(name=data.alarmName, log=self.log)
                alarm_info.callback = self.output_alarm
                self.alarms_info[alarm_info.name] = alarm_info

            alarm_info = self.alarms_info[data.alarmName]
            await alarm_info.set_from_data(data)

            if self.summary_state == salobj.State.ENABLED:
                await self.output_alarm(alarm_info, force_output=False)

    async def evt_logLevel_callback(self, data):
        """Handle logLevel event from the alarm subprocess."""
        self.log.info(f"Received logLevel event for {data.salIndex=} with {data.level=}")

    async def evt_logMessage_callback(self, data):
        """Handle logMessage event from the alarm subprocess."""
        self.log.debug(
            f"Received logMessage event for {data.salIndex=} with {data.message=}, {data.traceback=}"
        )


def run_watcher():
    """Run the Watcher CSC."""
    asyncio.run(WatcherCsc.amain(index=None))
