"""Pure selection and formatting helpers for additive native controls."""
from datetime import time
import re

_SCHEDULE = re.compile(r"PAGE-(?:OKRUH1\d+|TUV11)-US-(MON|TUE|WED|THU|FRI|SAT|SUN)-T(ON|OFF)([12])$")
_DURATIONS = {"TO-ADAPTACE-DOCASNEBEZCIDLACAS", "TUVMAXIMALNIDOBANATAPENI", "TUVDOBAKLIDU"}


def duration_prop(prop):
    """Only verified elapsed durations, not wall-clock schedule times."""
    return re.sub(r"^OKRUH\d+-", "TO-", prop.upper()) in _DURATIONS


def clock_control(metadata):
    """Only descriptor-writable clock times and native attenuation registers."""
    prop = metadata.get("prop", "")
    attrs = metadata.get("data", {}).get("attributes", {})
    config = metadata.get("descriptor_config", {})
    if not re.fullmatch(r"__R\d+_TIME_Thh:mm", attrs.get("internal_name", "")):
        return False
    return bool(_SCHEDULE.fullmatch(prop) or (
        config.get("time_control", False) and not duration_prop(prop)
        and (prop == "TSC-CAS" or re.fullmatch(r"TUVTPS-DAY[1-7][01]-ONTIME", prop))))


def clock_value(value):
    """Parse the controller's minute-resolution clock without guessing."""
    if not re.fullmatch(r"(?:[01]?\d|2[0-3]):[0-5]\d", str(value)):
        return None
    hours, minutes = map(int, value.split(":"))
    return time(hours, minutes)


def duration_minutes(value):
    """Parse an elapsed hh:mm value, allowing hours beyond 23."""
    if not re.fullmatch(r"\d+:[0-5]\d", str(value)):
        return None
    hours, minutes = map(int, value.split(":"))
    return hours * 60 + minutes


def duration_value(minutes):
    """Write integer minutes in the controller's native hh:mm format."""
    if minutes < 0 or minutes != int(minutes):
        raise ValueError("Duration must be a non-negative whole number of minutes")
    hours, minutes = divmod(int(minutes), 60)
    return f"{hours:02d}:{minutes:02d}"


def schedule_name(prop):
    """Describe attenuation boundaries, never misleading heating ON/OFF."""
    match = _SCHEDULE.fullmatch(prop)
    if not match:
        return None
    day, edge, period = match.groups()
    return f"Attenuation — {day.title()} — period {period} {'start' if edge == 'ON' else 'end'}"


def native_number_step(prop, config, attributes):
    """Use register precision only for verified temperature controls."""
    precision = re.search(r"_REAL_\.(\d+)f$", attributes.get("internal_name", ""))
    base = re.sub(r"^OKRUH\d+-", "TO-", prop.upper())
    temperature = (config.get("unit") == "°C" or base in {
        "TUVMINIMALNI", "TUVUTLUM", "TUVUTLUMMIN", "TO-HYSTEREZEPOKOJOVETEPLOTY",
        "TO-ADAPTACE-HYSTEREZEH", "TO-ADAPTACE-HYSTEREZEL",
    })
    if precision and temperature and not config.get("step_explicit"):
        return 10 ** (-int(precision.group(1)))
    return config.get("step")
