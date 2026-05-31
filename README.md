# Bus Charging Scheduler

Python + Streamlit take-home assignment for scheduling electric bus charging along the Bengaluru to Kochi route.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app opens with a scenario dropdown, the scenario input data, the per-bus timetable, and the per-station charger order.

## Data files

All scenarios live in `scenarios/*.json`. A scenario describes the complete scheduling world:

- route nodes and segment distances
- travel speed
- vehicle battery range and charge duration
- charging stations and charger counts
- scoring weights
- buses, operators, directions, and departure times

## Change a weight

Edit the `weights` object in a scenario file:

```json
"weights": {
  "individual": 1.0,
  "operator": 2.0,
  "overall": 1.0
}
```

The scheduler reads those values directly when scoring candidate charging plans.

## Add a new scenario

Copy one of the existing JSON files in `scenarios/`, give it a new `id` and `name`, and change the buses or route data. The Streamlit dropdown automatically includes it.

## Add a new rule

The current scheduler uses a weighted score in `scheduler/engine.py`:

```python
score = (
    weights.get("individual", 1.0) * individual
    + weights.get("operator", 1.0) * operator
    + weights.get("overall", 1.0) * overall
)
```

To add a new soft rule, add the required data to the scenario file, compute the rule value inside `_score_candidate`, and add a new weight key. Hard rules should be enforced either when generating feasible plans or during validation.

Example: to discourage charging at an expensive station, add `energy_cost_weight` to `weights` and station cost metadata to `charging_stations`, then include that term in `_score_candidate`.

## Assumptions

- Travel speed is 60 km/h, so 1 km takes 1 minute.
- Charging always takes exactly 25 minutes and fills the battery to full.
- Buses start from Bengaluru or Kochi fully charged.
- Endpoints are not scheduled chargers.
- The scheduler is allowed to choose two or more intermediate charging stops.
- When multiple feasible plans exist, the scheduler chooses the lowest weighted score.
