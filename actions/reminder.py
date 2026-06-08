import json
import os
import shutil
import subprocess
import sys
import calendar
from datetime import datetime, timedelta
from pathlib import Path

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _get_os() -> str:
    try:
        cfg = json.loads(
            (_base_dir() / "config" / "api_keys.json").read_text(encoding="utf-8")
        )
        return cfg.get("os_system", "windows").lower()
    except Exception:
        return "windows"


def _scripts_dir() -> Path:
    d = Path.home() / ".emily" / "reminders"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sanitise(text: str, max_len: int = 200) -> str:
    return (
        text.replace("\\", "")
            .replace('"', "")
            .replace("'", "")
            .replace("\n", " ")
            .replace("\r", "")
            .strip()
    )[:max_len]


def _emily_root_json() -> str:
    return json.dumps(str(_base_dir()))


def _script_preamble() -> str:
    return f"""import json
import sys
from pathlib import Path

EMILY_ROOT = Path({_emily_root_json()})
if str(EMILY_ROOT) not in sys.path:
    sys.path.insert(0, str(EMILY_ROOT))
"""


def _tts_snippet(text_expr: str) -> str:
    return f"""
try:
    from core.tts import speak_sync
    speak_sync({text_expr})
except Exception as _tts_err:
    print("TTS error:", _tts_err)
"""


def _llm_task_block(prompt_literal: str, action_type: str) -> str:
    return _script_preamble() + f"""
memory_path = EMILY_ROOT / "memory" / "long_term.json"

from core.tts import speak_sync
from core.llm.factory import get_llm_provider, run_completion_with_search
from core.llm.helpers import llm_complete

name = "sir"
city = ""
try:
    if memory_path.exists():
        mem = json.loads(memory_path.read_text(encoding="utf-8"))
        name = mem.get("identity", {{}}).get("name", {{}}).get("value", "sir")
        city = mem.get("identity", {{}}).get("city", {{}}).get("value", "")
except Exception:
    pass

try:
    base_prompt = {prompt_literal}
    context = f"\\n\\nUser context: Name is '{{name}}'."
    if city:
        context += f" City is '{{city}}'."
    final_prompt = base_prompt + context

    print("Querying LLM...")
    provider = get_llm_provider()
    if provider.supports_search():
        summary = run_completion_with_search(final_prompt)
    else:
        summary = llm_complete(final_prompt)

    try:
        from plyer import notification
        preview = summary[:200] + ("…" if len(summary) > 200 else "")
        notification.notify(title="E.M.I.L.Y. Briefing", message=preview, timeout=12)
    except Exception:
        pass

    speak_sync(summary)
except Exception as e:
    err_msg = f"Sir, I failed to complete the scheduled task ({action_type}). {{e}}"
    print(err_msg)
    speak_sync(err_msg)
"""


def _write_notify_script(task_name: str, message: str, os_name: str,
                         action_type: str = "notify", recurrence: str = "once",
                         custom_task_prompt: str = "") -> Path:
    script_path = _scripts_dir() / f"{task_name}.py"
    msg_literal = json.dumps(message)
    prompt_literal = ""

    # Set up prompt based on action_type
    if action_type == "news_briefing":
        prompt_literal = json.dumps(
            "Perform a Google Search for the top world news and technology news right now. "
            "Summarize the major headlines of today in a professional, brief, conversational update. "
            "Address the user as 'sir'. Warmly introduce the briefing."
        )
    elif action_type == "weather":
        prompt_literal = json.dumps(
            "Perform a Google Search for the current weather and forecast for the user's city. "
            "Provide a warm, friendly, brief weather report. Address the user as 'sir'."
        )
    elif action_type == "custom_llm_task":
        prompt_literal = json.dumps(custom_task_prompt or message)

    tts_block = _tts_snippet("message")

    if action_type == "notify":
        # Simple notify behavior (the original one)
        if os_name == "windows":
            notify_block = _script_preamble() + f"""
message = {msg_literal}
notified = False

try:
    from plyer import notification
    notification.notify(title="E.M.I.L.Y. Reminder", message=message, timeout=15)
    notified = True
except Exception:
    pass

if not notified:
    try:
        from win10toast import ToastNotifier
        ToastNotifier().show_toast("E.M.I.L.Y. Reminder", message, duration=15, threaded=False)
        notified = True
    except Exception:
        pass

if not notified:
    try:
        import subprocess
        subprocess.run(["msg", "*", "/TIME:30", message], check=False)
    except Exception:
        pass

try:
    import winsound
    for freq in [800, 1000, 1200]:
        winsound.Beep(freq, 180)
        import time; time.sleep(0.08)
except Exception:
    pass
""" + tts_block
        elif os_name == "mac":
            notify_block = _script_preamble() + f"""
message = {msg_literal}
notified = False

try:
    from plyer import notification
    notification.notify(title="E.M.I.L.Y. Reminder", message=message, timeout=15)
    notified = True
except Exception:
    pass

if not notified:
    try:
        import subprocess
        script = 'display notification "{{}}" with title "E.M.I.L.Y. Reminder"'.format(
            message.replace('"', '')
        )
        subprocess.run(["osascript", "-e", script], check=False)
    except Exception:
        pass
""" + tts_block
        else:  # linux
            notify_block = _script_preamble() + f"""
message = {msg_literal}
notified = False

try:
    from plyer import notification
    notification.notify(title="E.M.I.L.Y. Reminder", message=message, timeout=15)
    notified = True
except Exception:
    pass

if not notified:
    try:
        import subprocess
        subprocess.run(
            ["notify-send", "--urgency=normal", "--expire-time=15000",
             "E.M.I.L.Y. Reminder", message],
            check=False
        )
    except Exception:
        pass
""" + tts_block
    else:
        notify_block = _llm_task_block(prompt_literal, action_type)

    # If recurrence is once, delete after firing
    if recurrence == "once":
        self_delete_block = """
try:
    pathlib.Path(__file__).unlink(missing_ok=True)
except Exception:
    pass
"""
    else:
        self_delete_block = ""

    script_body = f"""# Auto-generated by E.M.I.L.Y. scheduled task — do not edit
import pathlib
{notify_block}
{self_delete_block}
"""
    script_path.write_text(script_body, encoding="utf-8")
    script_path.chmod(0o600)
    return script_path


def _schedule_windows(target_dt: datetime, task_name: str,
                      script_path: Path, message: str, recurrence: str = "once") -> str:
    python_exe = Path(sys.executable)
    pythonw = python_exe.parent / "pythonw.exe"
    if pythonw.exists():
        python_exe = pythonw

    xml_path = _scripts_dir() / f"{task_name}.xml"
    start_time_str = target_dt.strftime("%Y-%m-%dT%H:%M:%S")

    if recurrence == "daily":
        trigger_block = (
            '    <CalendarTrigger>\n'
            f'      <StartBoundary>{start_time_str}</StartBoundary>\n'
            '      <Enabled>true</Enabled>\n'
            '      <ScheduleByDay>\n'
            '        <DaysInterval>1</DaysInterval>\n'
            '      </ScheduleByDay>\n'
            '    </CalendarTrigger>\n'
        )
    elif recurrence == "weekly":
        day_of_week = target_dt.strftime("%A")
        trigger_block = (
            '    <CalendarTrigger>\n'
            f'      <StartBoundary>{start_time_str}</StartBoundary>\n'
            '      <Enabled>true</Enabled>\n'
            '      <ScheduleByWeek>\n'
            '        <WeeksInterval>1</WeeksInterval>\n'
            '        <DaysOfWeek>\n'
            f'          <{day_of_week}/>\n'
            '        </DaysOfWeek>\n'
            '      </ScheduleByWeek>\n'
            '    </CalendarTrigger>\n'
        )
    elif recurrence == "monthly":
        day_of_month = target_dt.day
        trigger_block = (
            '    <CalendarTrigger>\n'
            f'      <StartBoundary>{start_time_str}</StartBoundary>\n'
            '      <Enabled>true</Enabled>\n'
            '      <ScheduleByMonth>\n'
            f'        <DaysOfMonth><Day>{day_of_month}</Day></DaysOfMonth>\n'
            '        <Months><AllMonths/></Months>\n'
            '      </ScheduleByMonth>\n'
            '    </CalendarTrigger>\n'
        )
    else:  # once
        trigger_block = (
            '    <TimeTrigger>\n'
            f'      <StartBoundary>{start_time_str}</StartBoundary>\n'
            '      <Enabled>true</Enabled>\n'
            '    </TimeTrigger>\n'
        )

    xml_content = (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        '  <RegistrationInfo><Description>E.M.I.L.Y. Scheduled Task</Description></RegistrationInfo>\n'
        '  <Triggers>\n'
        f'{trigger_block}'
        '  </Triggers>\n'
        '  <Actions><Exec>\n'
        f'    <Command>{python_exe}</Command>\n'
        f'    <Arguments>"{script_path}"</Arguments>\n'
        '  </Exec></Actions>\n'
        '  <Settings>\n'
        '    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n'
        '    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n'
        '    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n'
        '    <StartWhenAvailable>true</StartWhenAvailable>\n'
        '    <ExecutionTimeLimit>PT15M</ExecutionTimeLimit>\n'
        '    <Enabled>true</Enabled>\n'
        '  </Settings>\n'
        '  <Principals><Principal>\n'
        '    <LogonType>InteractiveToken</LogonType>\n'
        '    <RunLevel>LeastPrivilege</RunLevel>\n'
        '  </Principal></Principals>\n'
        '</Task>'
    )

    xml_path.write_text(xml_content, encoding="utf-16")

    result = subprocess.run(
        ["schtasks", "/Create", "/TN", task_name, "/XML", str(xml_path), "/F"],
        capture_output=True, text=True,
    )

    try:
        xml_path.unlink(missing_ok=True)
    except Exception:
        pass

    if result.returncode != 0:
        script_path.unlink(missing_ok=True)
        err = (result.stderr or result.stdout).strip()
        print(f"[Reminder] ❌ schtasks: {err}")
        return ""

    return task_name


def _schedule_mac(target_dt: datetime, task_name: str,
                  script_path: Path, recurrence: str = "once") -> str:
    agents_dir = Path.home() / "Library" / "LaunchAgents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    label     = f"com.emily.reminder.{task_name}"
    plist_path = agents_dir / f"{label}.plist"

    calendar_interval = f"    <key>Hour</key>   <integer>{target_dt.hour}</integer>\n    <key>Minute</key> <integer>{target_dt.minute}</integer>"
    if recurrence == "once":
        calendar_interval += f"\n    <key>Year</key>   <integer>{target_dt.year}</integer>\n    <key>Month</key>  <integer>{target_dt.month}</integer>\n    <key>Day</key>    <integer>{target_dt.day}</integer>"
    elif recurrence == "weekly":
        calendar_interval += f"\n    <key>Weekday</key> <integer>{target_dt.isoweekday()}</integer>"
    elif recurrence == "monthly":
        calendar_interval += f"\n    <key>Day</key>    <integer>{target_dt.day}</integer>"

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>             <string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{sys.executable}</string>
    <string>{script_path}</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
{calendar_interval}
  </dict>
  <key>RunAtLoad</key>         <false/>
  <key>StandardOutPath</key>   <string>/dev/null</string>
  <key>StandardErrorPath</key> <string>/dev/null</string>
</dict>
</plist>
"""
    plist_path.write_text(plist_content, encoding="utf-8")
    plist_path.chmod(0o644)

    result = subprocess.run(
        ["launchctl", "load", str(plist_path)],
        capture_output=True, text=True,
    )

    if result.returncode != 0:
        plist_path.unlink(missing_ok=True)
        script_path.unlink(missing_ok=True)
        print(f"[Reminder] ❌ launchctl: {result.stderr.strip()}")
        return ""

    return label


def _schedule_linux(target_dt: datetime, task_name: str,
                    script_path: Path, recurrence: str = "once") -> str:
    if shutil.which("systemd-run"):
        if recurrence == "daily":
            on_calendar = f"*-*-* {target_dt.strftime('%H:%M:00')}"
        elif recurrence == "weekly":
            day_abbr = target_dt.strftime('%a')
            on_calendar = f"{day_abbr} *-*-* {target_dt.strftime('%H:%M:00')}"
        elif recurrence == "monthly":
            on_calendar = f"*-*-{target_dt.day:02d} {target_dt.strftime('%H:%M:00')}"
        else:
            on_calendar = target_dt.strftime("%Y-%m-%d %H:%M:00")

        result = subprocess.run(
            [
                "systemd-run",
                "--user",
                f"--on-calendar={on_calendar}",
                f"--unit={task_name}",
                "--",
                sys.executable, str(script_path),
            ],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return task_name
        print(f"[Reminder] ⚠️ systemd-run failed: {result.stderr.strip()}, trying 'at' / 'cron'")

    # Fallback to at / cron
    if recurrence == "once" and shutil.which("at"):
        at_time = target_dt.strftime("%H:%M %Y-%m-%d")
        cmd_str = f"{sys.executable} {script_path}\n"
        result  = subprocess.run(
            ["at", at_time],
            input=cmd_str, capture_output=True, text=True,
        )
        if result.returncode == 0:
            return task_name
        print(f"[Reminder] ❌ at: {result.stderr.strip()}")

    # Cron schedule daily / weekly / monthly fallback
    try:
        cron_expr = ""
        m, h = target_dt.minute, target_dt.hour
        if recurrence == "daily":
            cron_expr = f"{m} {h} * * *"
        elif recurrence == "weekly":
            # cron is 0-6 (0 is Sunday, 1 is Monday...) or 1-7 depending on OS, standard: 1-7 (Mon-Sun)
            cron_expr = f"{m} {h} * * {target_dt.isoweekday()}"
        elif recurrence == "monthly":
            cron_expr = f"{m} {h} {target_dt.day} * *"

        if cron_expr:
            cron_cmd = f'(crontab -l 2>/dev/null; echo "{cron_expr} {sys.executable} {script_path}") | crontab -'
            subprocess.run(cron_cmd, shell=True, check=True)
            return task_name
    except Exception as e:
        print(f"[Reminder] ❌ Linux cron fallback error: {e}")

    return ""


def _resolve_target_dt(
    date_str: str,
    time_str: str,
    recurrence: str,
    parameters: dict,
) -> tuple[datetime | None, str | None]:
    """
    Resolve when a reminder should fire.
    Prefer minutes_from_now for relative requests like "in five minutes".
    """
    minutes_from_now = parameters.get("minutes_from_now")
    if minutes_from_now is not None and str(minutes_from_now).strip() != "":
        try:
            mins = max(1, int(minutes_from_now))
            target_dt = datetime.now().replace(second=0, microsecond=0) + timedelta(minutes=mins)
            if target_dt <= datetime.now():
                target_dt += timedelta(minutes=1)
            return target_dt, None
        except (TypeError, ValueError):
            pass

    if not date_str or not time_str:
        return None, "I need both a date and a time to set a reminder or task."

    parsed = None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(f"{date_str} {time_str}", fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        return None, "I couldn't parse that date or time. Please use YYYY-MM-DD and HH:MM."

    now = datetime.now()
    target_dt = parsed

    if target_dt <= now:
        if recurrence in ("daily", "weekly", "monthly"):
            while target_dt <= now:
                if recurrence == "daily":
                    target_dt += timedelta(days=1)
                elif recurrence == "weekly":
                    target_dt += timedelta(weeks=1)
                elif recurrence == "monthly":
                    days_in_month = calendar.monthrange(target_dt.year, target_dt.month)[1]
                    target_dt += timedelta(days=days_in_month)
        else:
            # One-shot: if the model was only a little late, bump forward instead of failing
            late_by_sec = (now - target_dt).total_seconds()
            if late_by_sec <= 120:
                target_dt = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
                if target_dt <= now:
                    target_dt += timedelta(minutes=1)
            else:
                return None, "That time has already passed — I can't schedule a task in the past."

    return target_dt, None


def reminder(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    date_str = parameters.get("date", "").strip()
    time_str = parameters.get("time", "").strip()
    message  = parameters.get("message", "Reminder").strip()
    recurrence = parameters.get("recurrence", "once").strip().lower()
    action_type = parameters.get("action_type", "notify").strip().lower()
    custom_task_prompt = parameters.get("custom_task_prompt", "").strip()

    if not date_str or not time_str:
        return "I need both a date and a time to set a reminder or task."

    if recurrence not in ("once", "daily", "weekly", "monthly"):
        recurrence = "once"

    if action_type not in ("notify", "news_briefing", "weather", "custom_llm_task"):
        action_type = "notify"

    target_dt, err = _resolve_target_dt(date_str, time_str, recurrence, parameters)
    if err:
        return err
    assert target_dt is not None
    date_str = target_dt.strftime("%Y-%m-%d")
    time_str = target_dt.strftime("%H:%M")

    os_name    = _get_os()
    safe_msg   = _sanitise(message)
    task_name  = f"EMILYTask_{action_type}_{recurrence}_{target_dt.strftime('%Y%m%d_%H%M%S')}"

    try:
        script_path = _write_notify_script(task_name, safe_msg, os_name, action_type, recurrence, custom_task_prompt)
    except Exception as e:
        return f"Could not prepare the scheduled script: {e}"

    try:
        if os_name == "windows":
            job_id = _schedule_windows(target_dt, task_name, script_path, safe_msg, recurrence)
        elif os_name == "mac":
            job_id = _schedule_mac(target_dt, task_name, script_path, recurrence)
        else:
            job_id = _schedule_linux(target_dt, task_name, script_path, recurrence)
    except Exception as e:
        script_path.unlink(missing_ok=True)
        print(f"[Reminder] ❌ Scheduling exception: {e}")
        return "Something went wrong while scheduling the task."

    if not job_id:
        return "I couldn't register the task with the system scheduler."

    if player:
        player.write_log(f"[Reminder] Scheduled [{action_type}] ({recurrence}) for {date_str} {time_str}")

    friendly_time = target_dt.strftime("%B %d at %I:%M %p")
    rec_msg = f"every {recurrence[:-2]}" if recurrence != "once" else "once"
    if recurrence == "daily":
        rec_msg = "every day"
    elif recurrence == "weekly":
        rec_msg = "every week"

    return f"Task scheduled: '{message}' ({action_type}) to run {rec_msg} starting {friendly_time}."
