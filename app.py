from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from scheduler import run_scheduler
from scheduler.engine import format_time


SCENARIO_DIR = Path(__file__).parent / "scenarios"


@st.cache_data
def load_scenarios() -> dict[str, dict[str, Any]]:
    scenarios = {}
    for path in sorted(SCENARIO_DIR.glob("*.json")):
        scenario = json.loads(path.read_text())
        scenarios[scenario["name"]] = scenario
    return scenarios


def bus_input_frame(scenario: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(scenario["buses"])[["id", "operator", "direction", "departure"]]


def route_frame(scenario: dict[str, Any]) -> pd.DataFrame:
    nodes = scenario["route"]["nodes"]
    segments = scenario["route"]["segments_km"]
    return pd.DataFrame(
        {
            "from": nodes[:-1],
            "to": nodes[1:],
            "distance_km": segments,
        }
    )


def station_input_frame(scenario: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(scenario["charging_stations"]).rename(
        columns={"node": "station", "chargers": "charger_count"}
    )


def per_bus_frame(result: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for bus in result["buses"]:
        charge_summary = []
        for event in bus["events"]:
            charge_summary.append(
                f"{event['station']} {format_time(event['start'])}-{format_time(event['end'])}"
                f" (wait {int(round(event['wait']))} min)"
            )
        rows.append(
            {
                "bus_id": bus["bus_id"],
                "operator": bus["operator"],
                "direction": bus["direction"],
                "departure": format_time(bus["departure"]),
                "charging_plan": " -> ".join(bus["charging_plan"]),
                "charges": "; ".join(charge_summary),
                "total_wait_min": int(round(bus["total_wait"])),
                "arrival": format_time(bus["arrival"]),
            }
        )
    return pd.DataFrame(rows)


def event_frame(events: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for order, event in enumerate(events, start=1):
        rows.append(
            {
                "order": order,
                "bus_id": event["bus_id"],
                "operator": event["operator"],
                "direction": event["direction"],
                "charger": event["charger"],
                "station_arrival": format_time(event["arrival"]),
                "charge_start": format_time(event["start"]),
                "charge_end": format_time(event["end"]),
                "wait_min": int(round(event["wait"])),
            }
        )
    return pd.DataFrame(rows)


def render_metrics(result: dict[str, Any]) -> None:
    buses = result["buses"]
    total_wait = sum(bus["total_wait"] for bus in buses)
    max_wait = max(bus["total_wait"] for bus in buses) if buses else 0
    latest_arrival = max(bus["arrival"] for bus in buses) if buses else 0

    col1, col2, col3 = st.columns(3)
    col1.metric("Total wait", f"{int(round(total_wait))} min")
    col2.metric("Max bus wait", f"{int(round(max_wait))} min")
    col3.metric("Latest arrival", format_time(latest_arrival))


def main() -> None:
    st.set_page_config(page_title="Bus Charging Scheduler", layout="wide")
    st.title("Bus Charging Scheduler")

    scenarios = load_scenarios()
    scenario_name = st.selectbox("Scenario", list(scenarios.keys()))
    scenario = scenarios[scenario_name]
    result = run_scheduler(scenario)

    if result["validation_errors"]:
        st.error("Schedule is invalid.")
        st.write(result["validation_errors"])
    else:
        st.success("Schedule valid: range, route order, and charger-capacity constraints are satisfied.")

    render_metrics(result)

    with st.expander("Scenario input", expanded=True):
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            st.subheader("Buses")
            st.dataframe(bus_input_frame(scenario), use_container_width=True, hide_index=True)
        with c2:
            st.subheader("Route")
            st.dataframe(route_frame(scenario), use_container_width=True, hide_index=True)
        with c3:
            st.subheader("Chargers and weights")
            st.dataframe(station_input_frame(scenario), use_container_width=True, hide_index=True)
            st.json(scenario["weights"], expanded=True)

    st.subheader("Per-bus timetable")
    st.dataframe(per_bus_frame(result), use_container_width=True, hide_index=True)

    st.subheader("Per-station charger order")
    tabs = st.tabs(list(result["stations"].keys()))
    for tab, station in zip(tabs, result["stations"].keys()):
        with tab:
            st.dataframe(event_frame(result["stations"][station]), use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
