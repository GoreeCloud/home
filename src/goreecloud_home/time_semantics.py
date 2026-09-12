from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from math import acos, asin, cos, degrees, floor, isfinite, radians, sin, tan

MAX_CALENDAR_WINDOW_DAYS = 366
_SOLAR_ZENITH_DEGREES = 90.833


class SolarEvent(str, Enum):
    SUNRISE = "sunrise"
    SUNSET = "sunset"


@dataclass(frozen=True, slots=True)
class SolarCoordinates:
    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if isinstance(self.latitude, bool) or isinstance(self.longitude, bool):
            raise ValueError("solar coordinates must be numeric degrees")
        latitude = float(self.latitude)
        longitude = float(self.longitude)
        if not isfinite(latitude) or not -90.0 <= latitude <= 90.0:
            raise ValueError("solar latitude must be finite and between -90 and 90 degrees")
        if not isfinite(longitude) or not -180.0 <= longitude <= 180.0:
            raise ValueError("solar longitude must be finite and between -180 and 180 degrees")
        object.__setattr__(self, "latitude", latitude)
        object.__setattr__(self, "longitude", longitude)


@dataclass(frozen=True, slots=True)
class CalendarDateWindow:
    """Inclusive controller-local calendar-date window with a bounded span."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if type(self.start) is not date or type(self.end) is not date:
            raise ValueError("calendar window bounds must be date values")
        if self.end < self.start:
            raise ValueError("calendar window end must not precede start")
        if (self.end - self.start).days > MAX_CALENDAR_WINDOW_DAYS:
            raise ValueError(
                f"calendar window may span at most {MAX_CALENDAR_WINDOW_DAYS} days"
            )

    def contains(self, at: datetime) -> bool:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("calendar evaluation requires a timezone-aware datetime")
        return self.start <= at.date() <= self.end


def solar_event_utc(
    day: date,
    coordinates: SolarCoordinates,
    event: SolarEvent | str,
) -> datetime | None:
    """Return the UTC instant for a local-solar-date sunrise or sunset.

    The calculation is deterministic and dependency-free, using the NOAA solar-position
    equations with the standard 90.833-degree apparent-horizon zenith. Coordinates are
    caller-supplied for this calculation only; this module does not persist or discover
    household location. Polar dates without the requested horizon crossing return None.
    """

    if type(day) is not date:
        raise ValueError("solar event day must be a date value")
    event = SolarEvent(event)

    julian_day = _julian_day(day)
    century = _julian_century(julian_day)
    solar_noon_minutes = 720.0 - (4.0 * coordinates.longitude) - _equation_of_time(century)

    # Recompute declination/equation of time near local solar noon to reduce the
    # approximation error while keeping the calculation deterministic.
    noon_century = _julian_century(julian_day + (solar_noon_minutes / 1440.0))
    declination = radians(_sun_declination(noon_century))
    latitude = radians(coordinates.latitude)
    denominator = cos(latitude) * cos(declination)
    if abs(denominator) < 1e-15:
        return None

    cos_hour_angle = (
        cos(radians(_SOLAR_ZENITH_DEGREES)) / denominator
        - tan(latitude) * tan(declination)
    )
    if cos_hour_angle > 1.0 or cos_hour_angle < -1.0:
        return None

    hour_angle = degrees(acos(cos_hour_angle))
    signed_hour_angle = hour_angle if event is SolarEvent.SUNRISE else -hour_angle
    minutes_utc = (
        720.0
        - 4.0 * (coordinates.longitude + signed_hour_angle)
        - _equation_of_time(noon_century)
    )

    day_offset = floor(minutes_utc / 1440.0)
    minutes_in_day = minutes_utc - (day_offset * 1440.0)
    base = datetime.combine(day + timedelta(days=day_offset), time.min, tzinfo=timezone.utc)
    return base + timedelta(minutes=minutes_in_day)


def solar_events_utc(
    day: date,
    coordinates: SolarCoordinates,
) -> dict[SolarEvent, datetime | None]:
    return {
        SolarEvent.SUNRISE: solar_event_utc(day, coordinates, SolarEvent.SUNRISE),
        SolarEvent.SUNSET: solar_event_utc(day, coordinates, SolarEvent.SUNSET),
    }


def _julian_day(day: date) -> float:
    year = day.year
    month = day.month
    if month <= 2:
        year -= 1
        month += 12
    century = year // 100
    correction = 2 - century + (century // 4)
    return (
        floor(365.25 * (year + 4716))
        + floor(30.6001 * (month + 1))
        + day.day
        + correction
        - 1524.5
    )


def _julian_century(julian_day: float) -> float:
    return (julian_day - 2451545.0) / 36525.0


def _geom_mean_longitude(century: float) -> float:
    return (280.46646 + century * (36000.76983 + century * 0.0003032)) % 360.0


def _geom_mean_anomaly(century: float) -> float:
    return 357.52911 + century * (35999.05029 - 0.0001537 * century)


def _earth_orbit_eccentricity(century: float) -> float:
    return 0.016708634 - century * (0.000042037 + 0.0000001267 * century)


def _sun_equation_of_center(century: float) -> float:
    anomaly = radians(_geom_mean_anomaly(century))
    return (
        sin(anomaly) * (1.914602 - century * (0.004817 + 0.000014 * century))
        + sin(2.0 * anomaly) * (0.019993 - 0.000101 * century)
        + sin(3.0 * anomaly) * 0.000289
    )


def _sun_apparent_longitude(century: float) -> float:
    true_longitude = _geom_mean_longitude(century) + _sun_equation_of_center(century)
    omega = 125.04 - 1934.136 * century
    return true_longitude - 0.00569 - 0.00478 * sin(radians(omega))


def _obliquity_correction(century: float) -> float:
    seconds = 21.448 - century * (46.815 + century * (0.00059 - century * 0.001813))
    mean_obliquity = 23.0 + (26.0 + (seconds / 60.0)) / 60.0
    omega = 125.04 - 1934.136 * century
    return mean_obliquity + 0.00256 * cos(radians(omega))


def _sun_declination(century: float) -> float:
    obliquity = radians(_obliquity_correction(century))
    longitude = radians(_sun_apparent_longitude(century))
    return degrees(asin(sin(obliquity) * sin(longitude)))


def _equation_of_time(century: float) -> float:
    obliquity = radians(_obliquity_correction(century))
    longitude = radians(_geom_mean_longitude(century))
    eccentricity = _earth_orbit_eccentricity(century)
    anomaly = radians(_geom_mean_anomaly(century))
    y = tan(obliquity / 2.0) ** 2
    equation = (
        y * sin(2.0 * longitude)
        - 2.0 * eccentricity * sin(anomaly)
        + 4.0 * eccentricity * y * sin(anomaly) * cos(2.0 * longitude)
        - 0.5 * y * y * sin(4.0 * longitude)
        - 1.25 * eccentricity * eccentricity * sin(2.0 * anomaly)
    )
    return degrees(equation) * 4.0
