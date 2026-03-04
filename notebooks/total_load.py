"""
Title: Total Load
Description: Visualise ENTSO-E actual total load fetched by
             scripts/fetch_entsoe_load.py.
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
    # Total Load

    Visualises actual total electricity load downloaded from the
    [ENTSO-E Transparency Platform](https://transparency.entsoe.eu/) via
    `scripts/fetch_entsoe_load.py`.

    Use the controls below to pick countries, a date range and a time aggregation level.
    """)
    return


@app.cell
def _(Path, glob, mo, pl):
    _data_dir = Path(__file__).parent.parent / "data"
    _csv_files = sorted(glob.glob(str(_data_dir / "total_load_*.csv")))

    mo.stop(
        not _csv_files,
        mo.md(
            "No `total_load_*.csv` files found in `data/`. "
            "Run `scripts/fetch_entsoe_load.py` first."
        ),
    )

    _frames = []
    for _f in _csv_files:
        try:
            _frames.append(pl.read_csv(_f))
        except Exception:
            pass

    all_load = (
        pl.concat(_frames, how="diagonal_relaxed")
        .with_columns(
            pl.col("datetime_utc").str.to_datetime(format="%Y-%m-%dT%H:%M:%S%z", time_unit="us")
        )
        .unique(subset=["datetime_utc", "area"], keep="first")
        .sort(["area", "datetime_utc"])
    )
    return (all_load,)


@app.cell
def _(all_load, mo):
    _areas = sorted(all_load["area"].unique().to_list())

    country_picker = mo.ui.multiselect(
        options=_areas,
        value=_areas,
        label="Countries",
    )

    aggregation_picker = mo.ui.dropdown(
        options={"Raw (native resolution)": "raw", "Hourly": "1h", "Daily": "1d", "Weekly": "1w", "Monthly": "1mo"},
        value="Daily",
        label="Aggregation",
    )

    mo.hstack([country_picker, aggregation_picker], gap=2)
    return aggregation_picker, country_picker


@app.cell
def _(all_load, country_picker, mo, pl):
    _filtered = all_load.filter(pl.col("area").is_in(country_picker.value))
    _min_date = _filtered["datetime_utc"].min().date()
    _max_date = _filtered["datetime_utc"].max().date()

    date_range_picker = mo.ui.date_range(
        start=_min_date,
        stop=_max_date,
        value=(_min_date, _max_date),
        label="Date range",
        full_width=True,
    )
    date_range_picker
    return (date_range_picker,)


@app.cell
def _(aggregation_picker, all_load, country_picker, date_range_picker, mo, pl):
    _start, _end = date_range_picker.value

    filtered_load = (
        all_load
        .filter(
            pl.col("area").is_in(country_picker.value) &
            (pl.col("datetime_utc").dt.date() >= _start) &
            (pl.col("datetime_utc").dt.date() <= _end)
        )
    )

    mo.stop(
        filtered_load.is_empty(),
        mo.md("No data for the selected countries / date range."),
    )

    _agg = aggregation_picker.value
    if _agg == "raw":
        plot_load = filtered_load.select(["datetime_utc", "area", "load_mw"])
    else:
        plot_load = (
            filtered_load
            .sort("datetime_utc")
            .group_by_dynamic("datetime_utc", every=_agg, group_by="area")
            .agg(pl.col("load_mw").mean())
            .sort(["area", "datetime_utc"])
        )
    return filtered_load, plot_load


@app.cell
def _(go, pl, plot_load):
    _COUNTRY_COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]

    _fig = go.Figure()
    for _i, _area in enumerate(sorted(plot_load["area"].unique().to_list())):
        _ts = plot_load.filter(pl.col("area") == _area).sort("datetime_utc")
        _fig.add_trace(go.Scatter(
            x=_ts["datetime_utc"].to_list(),
            y=_ts["load_mw"].to_list(),
            name=_area,
            mode="lines",
            line=dict(width=1.5, color=_COUNTRY_COLORS[_i % len(_COUNTRY_COLORS)]),
            hovertemplate=f"<b>{_area}</b><br>%{{x|%Y-%m-%d}}<br>%{{y:,.0f}} MW<extra></extra>",
        ))

    _fig.update_layout(
        title="Actual Total Load",
        xaxis_title=None,
        yaxis_title="Load (MW)",
        hovermode="x unified",
        height=440,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=60, r=20, t=64, b=40),
    )
    _fig
    return


@app.cell
def _(date_range_picker, filtered_load, go, pl):
    _start, _end = date_range_picker.value

    # Monthly average load per country
    _monthly = (
        filtered_load
        .sort("datetime_utc")
        .group_by_dynamic("datetime_utc", every="1mo", group_by="area")
        .agg(pl.col("load_mw").mean())
        .sort(["area", "datetime_utc"])
    )

    _COUNTRY_COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]

    _fig2 = go.Figure()
    for _i, _area in enumerate(sorted(_monthly["area"].unique().to_list())):
        _ts = _monthly.filter(pl.col("area") == _area).sort("datetime_utc")
        _fig2.add_trace(go.Scatter(
            x=_ts["datetime_utc"].to_list(),
            y=_ts["load_mw"].to_list(),
            name=_area,
            mode="lines+markers",
            marker=dict(size=4),
            line=dict(width=2, color=_COUNTRY_COLORS[_i % len(_COUNTRY_COLORS)]),
            hovertemplate=f"<b>{_area}</b><br>%{{x|%Y-%m}}<br>%{{y:,.0f}} MW<extra></extra>",
        ))

    _fig2.update_layout(
        title=f"Monthly Average Load ({_start} to {_end})",
        xaxis_title=None,
        yaxis_title="Avg Load (MW)",
        hovermode="x unified",
        height=360,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=60, r=20, t=64, b=40),
    )
    _fig2
    return


@app.cell
def _(filtered_load, go, pl):
    # Hour-of-day profile: average load by hour across all selected data
    _hourly_profile = (
        filtered_load
        .with_columns(pl.col("datetime_utc").dt.hour().alias("hour"))
        .group_by(["area", "hour"])
        .agg(pl.col("load_mw").mean())
        .sort(["area", "hour"])
    )

    _COUNTRY_COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]

    _fig3 = go.Figure()
    for _i, _area in enumerate(sorted(_hourly_profile["area"].unique().to_list())):
        _ts = _hourly_profile.filter(pl.col("area") == _area).sort("hour")
        _fig3.add_trace(go.Scatter(
            x=_ts["hour"].to_list(),
            y=_ts["load_mw"].to_list(),
            name=_area,
            mode="lines+markers",
            marker=dict(size=5),
            line=dict(width=2, color=_COUNTRY_COLORS[_i % len(_COUNTRY_COLORS)]),
            hovertemplate=f"<b>{_area}</b><br>Hour %{{x}}<br>%{{y:,.0f}} MW<extra></extra>",
        ))

    _fig3.update_layout(
        title="Average Load Profile by Hour of Day (UTC)",
        xaxis=dict(title="Hour (UTC)", tickmode="linear", dtick=2),
        yaxis_title="Avg Load (MW)",
        hovermode="x unified",
        height=320,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=60, r=20, t=64, b=40),
    )
    _fig3
    return


@app.cell
def _(filtered_load, mo, pl):
    mo.md("### Raw data"), mo.ui.table(
        filtered_load
        .with_columns(pl.col("datetime_utc").dt.strftime("%Y-%m-%d %H:%M %Z"))
        .select(["datetime_utc", "area", "load_mw", "resolution"])
        .sort(["datetime_utc", "area"]),
        page_size=20,
    )
    return


if __name__ == "__main__":
    app.run()
