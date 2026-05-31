# Architecture

## Approach

The solution uses a data-driven greedy scheduling framework.

For each bus, the scheduler:

1. Builds the ordered route for the bus direction.
2. Generates all feasible charging-station subsets that respect the 240 km range.
3. Simulates each feasible candidate against current charger availability.
4. Scores candidates using scenario-provided weights.
5. Commits the best candidate into the station queues.

This is intentionally lighter than a full optimization solver. The assignment scenarios are small, and the interview will likely test whether the model is understandable and extensible. The code keeps the hard constraints separate from the soft scoring so new rules can be added without rewriting the scheduling flow.

## Data Structure

Each scenario JSON file is the source of truth. It contains:

- `route.nodes`: ordered route nodes.
- `route.segments_km`: distance between adjacent nodes.
- `route.speed_kmph`: travel speed used by simulation.
- `vehicle.battery_range_km`: maximum range after a full charge.
- `vehicle.charge_time_min`: fixed charge duration.
- `charging_stations`: station node names and charger counts.
- `weights`: soft-rule weights.
- `buses`: bus id, operator, direction, and departure time.

The scheduler output is structured as:

- per-bus charging plan
- per-bus timeline events
- total wait and arrival time
- per-station ordered charger events
- validation errors, if any

## Why This Fits

The key requirement is not only solving 20 buses today, but handling changes tomorrow. A scenario is data, not code. The scheduler does not hardcode Bengaluru, Kochi, A, B, C, or D. It derives route order, station order, feasible plans, charger counts, and timings from the scenario.

## Anticipated Future Changes

### More stations

Add route nodes, segment distances, and charging station entries in JSON. The feasible-plan generator automatically considers the new stations.

### Different charger counts

Change the `chargers` value for any station. The scheduler models each charger as a separate availability slot.

### New operators

Add any operator string to buses. Operator wait tracking is keyed dynamically by operator name.

### More buses

Add rows to the `buses` list. Runtime grows with buses and feasible station subsets, but the engine does not require code changes.

### Different battery range or charge duration

Change `vehicle.battery_range_km` or `vehicle.charge_time_min`. Feasible plans and timeline simulation use those values directly.

### Different route geometry

Change `route.nodes` and `route.segments_km`. Directions are represented as `first_node->last_node` or `last_node->first_node`.

### Time-of-day electricity cost

Add station cost windows to the scenario and a new weighted scoring term. This is a soft rule, so it belongs in candidate scoring.

### Priority buses

Add a priority field to buses and a priority weight. This can be modeled as a scoring term or as a hard queue-order rule if the business requires it.

### Driver shift limits

Add shift metadata to buses and enforce it as a validation or hard feasibility rule.

### Multiple routes sharing stations

Represent each route in data and keep station names global. The station availability map can remain keyed by station node/id.

### Maintenance windows

Add unavailable intervals to charging stations. Candidate simulation can initialize charger availability or block time windows from those intervals.

## Weight Changes

Weights live in one obvious place per scenario:

```json
"weights": {
  "individual": 1.0,
  "operator": 1.0,
  "overall": 1.0
}
```

The current terms are:

- `individual`: penalizes wait for the bus being scheduled.
- `operator`: penalizes average wait for that operator's fleet.
- `overall`: penalizes total trip duration.

## Adding a Rule

Soft rules are added to the candidate score. Hard rules are added to feasible-plan generation or validation.

Example soft rule:

```python
station_cost = sum(cost_by_station[event["station"]] for event in events)
score += weights.get("station_cost", 0.0) * station_cost
```

Example hard rule:

```python
if bus_priority == "express" and station not in allowed_express_stations:
    reject_candidate()
```

## Assumptions

- The spec does not define exact speed; this implementation uses 60 km/h.
- If a bus reaches a charger before it is free, it waits at that station.
- The scheduler is greedy by departure order. It does not globally reorder bus departures.
- The objective is defensible operational scheduling, not proof of mathematical optimality.
- Metrics in the app are supporting information; the required views remain input, per-bus timetable, and per-station order.
