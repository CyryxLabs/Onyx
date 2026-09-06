import requests
from datetime import date, timedelta


def _number(value: object) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _aggregate_day(day: dict) -> dict:
    """Return a representative daily forecast backed by wttr hourly samples."""
    hourly = [item for item in day.get("hourly", []) if isinstance(item, dict)]
    if not hourly:
        return dict(day)
    representative = min(
        hourly,
        key=lambda item: abs(int(item.get("time", 0) or 0) - 1200),
    )
    result = {**day, **representative}
    for key in ("humidity", "windspeedKmph"):
        values = [_number(item.get(key)) for item in hourly]
        usable = [value for value in values if value is not None]
        if usable:
            result[key] = str(round(sum(usable) / len(usable)))
    # Whole-day temperature bounds are more useful than the noon sample.
    for key in ("mintempC", "maxtempC", "avgtempC"):
        if day.get(key) is not None:
            result[key] = day[key]
    return result


def _select_forecast(data: dict, when: str) -> tuple[dict, str] | None:
    normalized = when.lower().strip()
    if normalized in {"now", "current", "right now"}:
        return None
    day_offsets = {"today": 0, "tomorrow": 1, "day after tomorrow": 2}
    period_hours = {"morning": 900, "afternoon": 1500, "evening": 1800, "tonight": 2100}
    period = next((key for key in period_hours if key in normalized), None)
    day_text = normalized.replace(period or "", "").strip() or "today"
    if day_text in day_offsets:
        target = date.today() + timedelta(days=day_offsets[day_text])
    else:
        try:
            target = date.fromisoformat(day_text)
        except ValueError as exc:
            raise ValueError(
                "Unsupported weather time. Use now, today, tomorrow, day after tomorrow, "
                "YYYY-MM-DD, or add morning/afternoon/evening/tonight."
            ) from exc
    days = data.get("weather", [])
    selected = next((item for item in days if item.get("date") == target.isoformat()), None)
    if selected is None:
        raise ValueError(f"Forecast for {target.isoformat()} is outside the available range.")
    if period:
        hourly = selected.get("hourly", [])
        selected = min(
            hourly,
            key=lambda item: abs(int(item.get("time", 0)) - period_hours[period]),
            default=None,
        )
        if selected is None:
            raise ValueError(f"No {period} forecast is available for {target.isoformat()}.")
    else:
        selected = _aggregate_day(selected)
    return selected, f"{target.isoformat()}{' ' + period if period else ''}"


def weather_action(
    parameters: dict,
    player=None,
    session_memory=None,
) -> str:
    city     = parameters.get("city")
    when     = parameters.get("time", "today")

    if not city or not isinstance(city, str) or not city.strip():
        msg = "Sir, the city is missing for the weather report."
        _log(msg, player)
        return msg

    city = city.strip()
    when = (when or "today").strip()

    try:
        response = requests.get(
            f"https://wttr.in/{city}",
            params={"format": "j1"},
            headers={"User-Agent": "Onyx-CyryxLabs/1.0"},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        forecast = _select_forecast(data, when)
        if forecast is None:
            selected = data["current_condition"][0]
            label = "now"
            temp_c = selected.get("temp_C", "?")
            feels_c = selected.get("FeelsLikeC", "?")
            extra = f"{temp_c}°C (feels like {feels_c}°C)"
        else:
            selected, label = forecast
            temp_c = selected.get("tempC") or selected.get("avgtempC", "?")
            low = selected.get("mintempC")
            high = selected.get("maxtempC")
            extra = f"{temp_c}°C"
            if low is not None and high is not None:
                extra = f"low {low}°C, high {high}°C"
        description = selected.get("weatherDesc", [{}])[0].get("value", "unknown")
        humidity = selected.get("humidity", "?")
        wind_kph = selected.get("windspeedKmph", "?")
        msg = f"Weather in {city} for {label}: {description}, {extra}, humidity {humidity}%, wind {wind_kph} km/h."
    except ValueError as e:
        msg = str(e)
    except Exception as e:
        msg = f"Weather lookup failed for {city}: {e}"
        _log(msg, player)
        return msg
    _log(msg, player)

    if session_memory:
        try:
            session_memory.set_last_search(query=f"weather in {city} {when}", response=msg)
        except Exception:
            pass

    return msg


def _log(message: str, player=None) -> None:
    print(f"[Weather] {message}")
    if player:
        try:
            player.write_log(f"ONYX: {message}")
        except Exception:
            pass
