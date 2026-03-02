"""
Title: Cross-Border Physical Flows
Description: Visualise ENTSO-E cross-border electricity flows fetched by
             scripts/fetch_entsoe_flows.py.
"""

import marimo

__generated_with = "0.20.2"
app = marimo.App(width="full")


@app.cell
def _():
    import glob
    from pathlib import Path

    import marimo as mo
    import plotly.graph_objects as go
    import polars as pl

    return Path, glob, go, mo, pl


@app.cell
def _(mo):
    mo.md("""
    # Cross-Border Physical Flows

    Visualises hourly / 15-minute cross-border electricity flows downloaded from the
    [ENTSO-E Transparency Platform](https://transparency.entsoe.eu/) via
    `scripts/fetch_entsoe_flows.py`.

    Use the controls below to pick an interconnection, a date range and a time
    aggregation level.
    """)
    return


# ---------------------------------------------------------------------------
# Load all cross_border_flows CSV files from data/
# ---------------------------------------------------------------------------
@app.cell
def _(Path, glob, mo, pl):
    _data_dir = Path(__file__).parent.parent / "data"
    _csv_files = sorted(glob.glob(str(_data_dir / "cross_border_flows_*.csv")))

    mo.stop(
        not _csv_files,
        mo.md(
            "No `cross_border_flows_*.csv` files found in `data/`. "
            "Run `scripts/fetch_entsoe_flows.py` first."
        ),
    )

    _frames = []
    for _f in _csv_files:
        try:
            _frames.append(pl.read_csv(_f))
        except Exception as _e:
            pass  # skip malformed files silently

    all_flows = (
        pl.concat(_frames, how="diagonal_relaxed")
        .with_columns(
            pl.col("datetime_utc").str.to_datetime(format="%Y-%m-%dT%H:%M:%S%z", time_unit="us")
        )
        .sort("datetime_utc")
        .unique(subset=["datetime_utc", "out_country", "in_country"], keep="first")
    )

    return (all_flows,)


# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------
@app.cell
def _(all_flows, mo, pl):
    # Build sorted list of available interconnections as "AT → DE_LU" labels
    _pairs = (
        all_flows
        .select(["out_country", "in_country"])
        .unique()
        .sort(["out_country", "in_country"])
        .with_columns(
            (pl.col("out_country") + " → " + pl.col("in_country")).alias("label")
        )
    )
    _pair_labels = _pairs["label"].to_list()

    interconnection_picker = mo.ui.dropdown(
        options=_pair_labels,
        value=_pair_labels[0],
        label="Interconnection",
    )

    aggregation_picker = mo.ui.dropdown(
        options={"Raw (native resolution)": "raw", "Hourly": "1h", "Daily": "1d", "Weekly": "1w", "Monthly": "1mo"},
        value="Daily",
        label="Aggregation",
    )

    mo.hstack([interconnection_picker, aggregation_picker], gap=2)
    return aggregation_picker, interconnection_picker


@app.cell
def _(all_flows, mo, pl):
    _min_date = all_flows["datetime_utc"].min().date()
    _max_date = all_flows["datetime_utc"].max().date()

    date_range_picker = mo.ui.date_range(
        start=_min_date,
        stop=_max_date,
        value=(_min_date, _max_date),
        label="Date range",
        full_width=True,
    )
    date_range_picker
    return (date_range_picker,)


# ---------------------------------------------------------------------------
# Filter data for selected interconnection + date range
# ---------------------------------------------------------------------------
@app.cell
def _(aggregation_picker, all_flows, date_range_picker, interconnection_picker, mo, pl):
    _out, _in = interconnection_picker.value.split(" → ")
    _start, _end = date_range_picker.value

    filtered_flows = (
        all_flows
        .filter(
            (pl.col("out_country") == _out) &
            (pl.col("in_country") == _in) &
            (pl.col("datetime_utc").dt.date() >= _start) &
            (pl.col("datetime_utc").dt.date() <= _end)
        )
    )

    mo.stop(
        filtered_flows.is_empty(),
        mo.md(f"No data for **{interconnection_picker.value}** in the selected date range."),
    )

    agg = aggregation_picker.value
    if agg == "raw":
        plot_df = filtered_flows.select(["datetime_utc", "flow_mw"])
    else:
        plot_df = (
            filtered_flows
            .sort("datetime_utc")
            .group_by_dynamic("datetime_utc", every=agg)
            .agg(pl.col("flow_mw").mean().alias("flow_mw"))
            .sort("datetime_utc")
        )

    return filtered_flows, plot_df


# ---------------------------------------------------------------------------
# Time-series chart
# ---------------------------------------------------------------------------
@app.cell
def _(go, interconnection_picker, mo, plot_df):
    _fig = go.Figure()
    _fig.add_trace(go.Scatter(
        x=plot_df["datetime_utc"].to_list(),
        y=plot_df["flow_mw"].to_list(),
        mode="lines",
        line=dict(width=1),
        name="Flow (MW)",
        hovertemplate="%{x|%Y-%m-%d %H:%M}<br>%{y:,.0f} MW<extra></extra>",
    ))
    _fig.add_hline(y=0, line_dash="dot", line_color="grey", line_width=1)
    _fig.update_layout(
        title=f"Cross-Border Physical Flow: {interconnection_picker.value}",
        xaxis_title=None,
        yaxis_title="Flow (MW)",
        hovermode="x unified",
        height=420,
        margin=dict(l=60, r=20, t=48, b=40),
    )
    mo.plotly(_fig)
    return


# ---------------------------------------------------------------------------
# Net flow (A→B minus B→A) if reverse direction is available
# ---------------------------------------------------------------------------
@app.cell
def _(all_flows, date_range_picker, go, interconnection_picker, mo, pl):
    _out, _in = interconnection_picker.value.split(" → ")
    _start, _end = date_range_picker.value

    _fwd = (
        all_flows
        .filter(
            (pl.col("out_country") == _out) & (pl.col("in_country") == _in) &
            (pl.col("datetime_utc").dt.date() >= _start) &
            (pl.col("datetime_utc").dt.date() <= _end)
        )
        .select(["datetime_utc", pl.col("flow_mw").alias("fwd_mw")])
    )
    _rev = (
        all_flows
        .filter(
            (pl.col("out_country") == _in) & (pl.col("in_country") == _out) &
            (pl.col("datetime_utc").dt.date() >= _start) &
            (pl.col("datetime_utc").dt.date() <= _end)
        )
        .select(["datetime_utc", pl.col("flow_mw").alias("rev_mw")])
    )

    mo.stop(
        _rev.is_empty(),
        mo.md(f"Reverse direction **{_in} → {_out}** not available — skipping net flow chart."),
    )

    _net = (
        _fwd.join(_rev, on="datetime_utc", how="inner")
        .with_columns((pl.col("fwd_mw") - pl.col("rev_mw")).alias("net_mw"))
        .group_by_dynamic("datetime_utc", every="1d")
        .agg(pl.col("net_mw").mean())
        .sort("datetime_utc")
    )

    _fig2 = go.Figure()
    _fig2.add_trace(go.Bar(
        x=_net["datetime_utc"].to_list(),
        y=_net["net_mw"].to_list(),
        marker_color=[
            "steelblue" if v >= 0 else "tomato"
            for v in _net["net_mw"].to_list()
        ],
        name="Net flow (MW)",
        hovertemplate="%{x|%Y-%m-%d}<br>Net: %{y:,.0f} MW<extra></extra>",
    ))
    _fig2.update_layout(
        title=f"Daily Net Flow: {_out} → {_in} (positive = net export from {_out})",
        xaxis_title=None,
        yaxis_title="Net Flow (MW)",
        bargap=0,
        height=360,
        margin=dict(l=60, r=20, t=48, b=40),
    )
    mo.plotly(_fig2)
    return


# ---------------------------------------------------------------------------
# Monthly summary stats
# ---------------------------------------------------------------------------
@app.cell
def _(date_range_picker, go, interconnection_picker, mo, pl, all_flows):
    _out, _in = interconnection_picker.value.split(" → ")
    _start, _end = date_range_picker.value

    _monthly = (
        all_flows
        .filter(
            (pl.col("out_country") == _out) & (pl.col("in_country") == _in) &
            (pl.col("datetime_utc").dt.date() >= _start) &
            (pl.col("datetime_utc").dt.date() <= _end)
        )
        .sort("datetime_utc")
        .group_by_dynamic("datetime_utc", every="1mo")
        .agg(
            pl.col("flow_mw").mean().alias("mean_mw"),
            pl.col("flow_mw").max().alias("max_mw"),
            pl.col("flow_mw").min().alias("min_mw"),
        )
        .sort("datetime_utc")
    )

    _fig3 = go.Figure()
    _fig3.add_trace(go.Scatter(
        x=_monthly["datetime_utc"].to_list(),
        y=_monthly["max_mw"].to_list(),
        mode="lines",
        line=dict(width=0),
        showlegend=False,
        hoverinfo="skip",
    ))
    _fig3.add_trace(go.Scatter(
        x=_monthly["datetime_utc"].to_list(),
        y=_monthly["min_mw"].to_list(),
        mode="lines",
        fill="tonexty",
        fillcolor="rgba(70,130,180,0.2)",
        line=dict(width=0),
        name="Min–Max range",
        hovertemplate="%{x|%Y-%m}<br>Min: %{y:,.0f} MW<extra></extra>",
    ))
    _fig3.add_trace(go.Scatter(
        x=_monthly["datetime_utc"].to_list(),
        y=_monthly["mean_mw"].to_list(),
        mode="lines+markers",
        line=dict(color="steelblue", width=2),
        marker=dict(size=5),
        name="Monthly mean",
        hovertemplate="%{x|%Y-%m}<br>Mean: %{y:,.0f} MW<extra></extra>",
    ))
    _fig3.update_layout(
        title=f"Monthly Summary: {interconnection_picker.value}",
        xaxis_title=None,
        yaxis_title="Flow (MW)",
        hovermode="x unified",
        height=360,
        margin=dict(l=60, r=20, t=48, b=40),
    )
    mo.plotly(_fig3)
    return


# ---------------------------------------------------------------------------
# Raw data table (bottom of notebook)
# ---------------------------------------------------------------------------
@app.cell
def _(filtered_flows, mo, pl):
    mo.md("### Raw data"), mo.ui.table(
        filtered_flows
        .with_columns(pl.col("datetime_utc").dt.strftime("%Y-%m-%d %H:%M %Z"))
        .select(["datetime_utc", "out_country", "in_country", "flow_mw", "resolution"])
        .sort("datetime_utc", descending=True),
        page_size=20,
    )
    return


if __name__ == "__main__":
    app.run()
