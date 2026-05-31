from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any


MINUTES_PER_HOUR = 60


@dataclass(frozen=True)
class Stop:
    name: str
    distance_from_start: float
    is_charging_station: bool
    charger_count: int = 0


@dataclass(frozen=True)
class PlanCandidate:
    stations: tuple[str, ...]
    leg_distances: tuple[float, ...]


def parse_time(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def format_time(minutes: float) -> str:
    minutes = int(round(minutes))
    day_offset, minute_of_day = divmod(minutes, 24 * 60)
    hours, mins = divmod(minute_of_day, 60)
    suffix = f" +{day_offset}d" if day_offset else ""
    return f"{hours:02d}:{mins:02d}{suffix}"


def route_stops(scenario: dict[str, Any], direction: str) -> list[Stop]:
    route = scenario["route"]
    nodes = route["nodes"]
    segment_distances = route["segments_km"]
    distances = [0]
    for segment_distance in segment_distances:
        distances.append(distances[-1] + segment_distance)

    station_map = {
        station["node"]: station
        for station in scenario["charging_stations"]
    }
    stops = [
        Stop(
            name=node,
            distance_from_start=distance,
            is_charging_station=node in station_map,
            charger_count=station_map.get(node, {}).get("chargers", 0),
        )
        for node, distance in zip(nodes, distances)
    ]

    if direction == f"{nodes[0]}->{nodes[-1]}":
        return stops
    if direction == f"{nodes[-1]}->{nodes[0]}":
        total = distances[-1]
        return [
            Stop(
                name=stop.name,
                distance_from_start=total - stop.distance_from_start,
                is_charging_station=stop.is_charging_station,
                charger_count=stop.charger_count,
            )
            for stop in reversed(stops)
        ]

    raise ValueError(f"Unsupported direction: {direction}")


def feasible_plans(scenario: dict[str, Any], direction: str) -> list[PlanCandidate]:
    stops = route_stops(scenario, direction)
    max_range = scenario["vehicle"]["battery_range_km"]
    charging_stops = [stop for stop in stops if stop.is_charging_station]
    endpoint_distance = stops[-1].distance_from_start
    candidates: list[PlanCandidate] = []

    for count in range(len(charging_stops) + 1):
        for subset in combinations(charging_stops, count):
            distances = [0, *[stop.distance_from_start for stop in subset], endpoint_distance]
            leg_distances = tuple(b - a for a, b in zip(distances, distances[1:]))
            if all(leg <= max_range for leg in leg_distances):
                candidates.append(
                    PlanCandidate(
                        stations=tuple(stop.name for stop in subset),
                        leg_distances=leg_distances,
                    )
                )

    return sorted(candidates, key=lambda candidate: (len(candidate.stations), candidate.stations))


def _station_distances(stops: list[Stop]) -> dict[str, float]:
    return {stop.name: stop.distance_from_start for stop in stops}


def _operator_average_wait(operator_waits: dict[str, list[float]], operator: str, extra_wait: float) -> float:
    waits = [*operator_waits.get(operator, []), extra_wait]
    return sum(waits) / len(waits)


def _score_candidate(
    *,
    total_wait: float,
    arrival_time: float,
    departure_time: float,
    operator_average_wait: float,
    candidate: PlanCandidate,
    weights: dict[str, float],
) -> float:
    individual = total_wait
    operator = operator_average_wait
    overall = arrival_time - departure_time
    extra_charge_penalty = max(0, len(candidate.stations) - 2) * 8

    return (
        weights.get("individual", 1.0) * individual
        + weights.get("operator", 1.0) * operator
        + weights.get("overall", 1.0) * overall
        + extra_charge_penalty
    )


def _simulate_candidate(
    *,
    scenario: dict[str, Any],
    bus: dict[str, str],
    candidate: PlanCandidate,
    station_available: dict[str, list[float]],
) -> tuple[list[dict[str, Any]], float, float]:
    stops = route_stops(scenario, bus["direction"])
    distances = _station_distances(stops)
    speed_kmph = scenario["route"]["speed_kmph"]
    charge_minutes = scenario["vehicle"]["charge_time_min"]
    current_time = parse_time(bus["departure"])
    current_distance = 0.0
    events: list[dict[str, Any]] = []

    for station in candidate.stations:
        station_distance = distances[station]
        current_time += (station_distance - current_distance) / speed_kmph * MINUTES_PER_HOUR
        current_distance = station_distance

        charger_slots = station_available[station]
        charger_index, available_at = min(enumerate(charger_slots), key=lambda item: item[1])
        charge_start = max(current_time, available_at)
        charge_end = charge_start + charge_minutes
        wait = charge_start - current_time

        events.append(
            {
                "type": "charge",
                "station": station,
                "charger": charger_index + 1,
                "arrival": current_time,
                "start": charge_start,
                "end": charge_end,
                "wait": wait,
            }
        )
        current_time = charge_end

    final_distance = stops[-1].distance_from_start
    current_time += (final_distance - current_distance) / speed_kmph * MINUTES_PER_HOUR
    total_wait = sum(event["wait"] for event in events)
    return events, current_time, total_wait


def _commit_events(events: list[dict[str, Any]], station_available: dict[str, list[float]]) -> None:
    for event in events:
        station_available[event["station"]][event["charger"] - 1] = event["end"]


def validate_timeline(bus_result: dict[str, Any], scenario: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    max_range = scenario["vehicle"]["battery_range_km"]
    stops = route_stops(scenario, bus_result["direction"])
    distances = _station_distances(stops)
    points = [0.0, *[distances[event["station"]] for event in bus_result["events"]], stops[-1].distance_from_start]
    for start, end in zip(points, points[1:]):
        if end - start > max_range:
            errors.append(f"{bus_result['bus_id']} has invalid range leg: {end - start:.0f} km")
    return errors


def run_scheduler(scenario: dict[str, Any]) -> dict[str, Any]:
    station_available = {
        station["node"]: [0.0] * station["chargers"]
        for station in scenario["charging_stations"]
    }
    operator_waits: dict[str, list[float]] = {}
    bus_results: list[dict[str, Any]] = []

    buses = sorted(scenario["buses"], key=lambda bus: (parse_time(bus["departure"]), bus["id"]))
    weights = scenario.get("weights", {})

    for bus in buses:
        departure_time = parse_time(bus["departure"])
        best: tuple[float, PlanCandidate, list[dict[str, Any]], float, float] | None = None

        for candidate in feasible_plans(scenario, bus["direction"]):
            trial_availability = {station: slots[:] for station, slots in station_available.items()}
            events, arrival_time, total_wait = _simulate_candidate(
                scenario=scenario,
                bus=bus,
                candidate=candidate,
                station_available=trial_availability,
            )
            operator_average_wait = _operator_average_wait(operator_waits, bus["operator"], total_wait)
            score = _score_candidate(
                total_wait=total_wait,
                arrival_time=arrival_time,
                departure_time=departure_time,
                operator_average_wait=operator_average_wait,
                candidate=candidate,
                weights=weights,
            )
            if best is None or score < best[0]:
                best = (score, candidate, events, arrival_time, total_wait)

        if best is None:
            raise ValueError(f"No feasible charging plan for {bus['id']}")

        _, candidate, events, arrival_time, total_wait = best
        _commit_events(events, station_available)
        operator_waits.setdefault(bus["operator"], []).append(total_wait)
        bus_results.append(
            {
                "bus_id": bus["id"],
                "operator": bus["operator"],
                "direction": bus["direction"],
                "departure": departure_time,
                "charging_plan": list(candidate.stations),
                "events": events,
                "total_wait": total_wait,
                "arrival": arrival_time,
            }
        )

    station_results: dict[str, list[dict[str, Any]]] = {
        station["node"]: []
        for station in scenario["charging_stations"]
    }
    for result in bus_results:
        for event in result["events"]:
            station_results[event["station"]].append(
                {
                    "bus_id": result["bus_id"],
                    "operator": result["operator"],
                    "direction": result["direction"],
                    "charger": event["charger"],
                    "arrival": event["arrival"],
                    "start": event["start"],
                    "end": event["end"],
                    "wait": event["wait"],
                }
            )

    for events in station_results.values():
        events.sort(key=lambda event: (event["start"], event["charger"], event["bus_id"]))

    validation_errors = []
    for result in bus_results:
        validation_errors.extend(validate_timeline(result, scenario))

    return {
        "scenario_id": scenario["id"],
        "scenario_name": scenario["name"],
        "buses": bus_results,
        "stations": station_results,
        "validation_errors": validation_errors,
        "format_time": format_time,
    }
