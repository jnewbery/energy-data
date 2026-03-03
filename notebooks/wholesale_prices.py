"""
Title: Day-Ahead Energy Prices
Description: Visualise ENTSO-E day-ahead wholesale electricity prices fetched by
             scripts/fetch_entsoe_prices.py.
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
    # Day-Ahead Energy Prices

    Visualises wholesale day-ahead electricity prices (EUR/MWh) downloaded from the
    [ENTSO-E Transparency Platform](https://transparency.entsoe.eu/) via
    `scripts/fetch_entsoe_prices.py`.

    Use the controls below to pick countries, a date range and a time aggregation level.
    """)
    return


@app.cell
def _(Path, glob, mo, pl):
    _data_dir = Path(__file__).parent.parent / "data"
    _csv_files = sorted(glob.glob(str(_data_dir / "day_ahead_prices_*.csv")))

    mo.stop(
        not _csv_files,
        mo.md(
            "No `day_ahead_prices_*.csv` files found in `data/`. "
            "Run `scripts/fetch_entsoe_prices.py` first."
        ),
    )

    _frames = []
    for _f in _csv_files:
        try:
            _frames.append(pl.read_csv(_f))
        except Exception:
            pass

    all_prices = (
        pl.concat(_frames, how="diagonal_relaxed")
        .with_columns(
            pl.col("datetime_utc").str.to_datetime(format="%Y-%m-%dT%H:%M:%S%z", time_unit="us")
        )
        .unique(subset=["datetime_utc", "area"], keep="first")
        .sort(["area", "datetime_utc"])
    )
    return (all_prices,)


@app.cell
def _(all_prices, mo):
    _areas = sorted(all_prices["area"].unique().to_list())

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
def _(all_prices, country_picker, mo, pl):
    _filtered = all_prices.filter(pl.col("area").is_in(country_picker.value))
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
def _(
    aggregation_picker,
    all_prices,
    country_picker,
    date_range_picker,
    mo,
    pl,
):
    _start, _end = date_range_picker.value

    filtered_prices = (
        all_prices
        .filter(
            pl.col("area").is_in(country_picker.value) &
            (pl.col("datetime_utc").dt.date() >= _start) &
            (pl.col("datetime_utc").dt.date() <= _end)
        )
    )

    mo.stop(
        filtered_prices.is_empty(),
        mo.md("No data for the selected countries / date range."),
    )

    _agg = aggregation_picker.value
    if _agg == "raw":
        plot_prices = filtered_prices.select(["datetime_utc", "area", "price_eur_mwh"])
    else:
        plot_prices = (
            filtered_prices
            .sort("datetime_utc")
            .group_by_dynamic("datetime_utc", every=_agg, group_by="area")
            .agg(pl.col("price_eur_mwh").mean())
            .sort(["area", "datetime_utc"])
        )
    return filtered_prices, plot_prices


@app.cell
def _(go, pl, plot_prices):
    _COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]

    _fig = go.Figure()
    for _i, _area in enumerate(sorted(plot_prices["area"].unique().to_list())):
        _ts = plot_prices.filter(pl.col("area") == _area).sort("datetime_utc")
        _fig.add_trace(go.Scatter(
            x=_ts["datetime_utc"].to_list(),
            y=_ts["price_eur_mwh"].to_list(),
            name=_area,
            mode="lines",
            line=dict(width=1.5, color=_COLORS[_i % len(_COLORS)]),
            hovertemplate=f"<b>{_area}</b><br>%{{x|%Y-%m-%d}}<br>%{{y:,.2f}} EUR/MWh<extra></extra>",
        ))

    _fig.add_hline(y=0, line_dash="dot", line_color="grey", line_width=1)
    _fig.update_layout(
        title="Day-Ahead Energy Prices",
        xaxis_title=None,
        yaxis_title="Price (EUR/MWh)",
        hovermode="x unified",
        height=440,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=70, r=20, t=64, b=40),
    )
    _fig
    return


@app.cell
def _(date_range_picker, filtered_prices, go, pl):
    _start, _end = date_range_picker.value
    _COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]

    # Monthly mean ± 1 std band
    _monthly = (
        filtered_prices
        .sort("datetime_utc")
        .group_by_dynamic("datetime_utc", every="1mo", group_by="area")
        .agg(
            pl.col("price_eur_mwh").mean().alias("mean"),
            pl.col("price_eur_mwh").std().alias("std"),
        )
        .with_columns(
            (pl.col("mean") + pl.col("std")).alias("upper"),
            (pl.col("mean") - pl.col("std")).alias("lower"),
        )
        .sort(["area", "datetime_utc"])
    )

    _fig2 = go.Figure()
    for _i, _area in enumerate(sorted(_monthly["area"].unique().to_list())):
        _ts = _monthly.filter(pl.col("area") == _area).sort("datetime_utc")
        _color = _COLORS[_i % len(_COLORS)]
        _xs = _ts["datetime_utc"].to_list()
        _fig2.add_trace(go.Scatter(
            x=_xs + _xs[::-1],
            y=_ts["upper"].to_list() + _ts["lower"].to_list()[::-1],
            fill="toself",
            fillcolor=_color.replace(")", ",0.15)").replace("rgb", "rgba") if "rgb" in _color else f"rgba({int(_color[1:3],16)},{int(_color[3:5],16)},{int(_color[5:7],16)},0.15)",
            line=dict(color="rgba(0,0,0,0)"),
            showlegend=False,
            hoverinfo="skip",
        ))
        _fig2.add_trace(go.Scatter(
            x=_xs,
            y=_ts["mean"].to_list(),
            name=_area,
            mode="lines+markers",
            marker=dict(size=4),
            line=dict(width=2, color=_color),
            hovertemplate=f"<b>{_area}</b><br>%{{x|%Y-%m}}<br>Avg: %{{y:,.2f}} EUR/MWh<extra></extra>",
        ))

    _fig2.add_hline(y=0, line_dash="dot", line_color="grey", line_width=1)
    _fig2.update_layout(
        title=f"Monthly Average Price ± 1 std ({_start} to {_end})",
        xaxis_title=None,
        yaxis_title="Price (EUR/MWh)",
        hovermode="x unified",
        height=380,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=70, r=20, t=64, b=40),
    )
    _fig2
    return


@app.cell
def _(filtered_prices, go, pl):
    # Hour-of-day average price profile
    _hourly_profile = (
        filtered_prices
        .with_columns(pl.col("datetime_utc").dt.hour().alias("hour"))
        .group_by(["area", "hour"])
        .agg(pl.col("price_eur_mwh").mean())
        .sort(["area", "hour"])
    )

    _COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]

    _fig3 = go.Figure()
    for _i, _area in enumerate(sorted(_hourly_profile["area"].unique().to_list())):
        _ts = _hourly_profile.filter(pl.col("area") == _area).sort("hour")
        _fig3.add_trace(go.Scatter(
            x=_ts["hour"].to_list(),
            y=_ts["price_eur_mwh"].to_list(),
            name=_area,
            mode="lines+markers",
            marker=dict(size=5),
            line=dict(width=2, color=_COLORS[_i % len(_COLORS)]),
            hovertemplate=f"<b>{_area}</b><br>Hour %{{x}}<br>%{{y:,.2f}} EUR/MWh<extra></extra>",
        ))

    _fig3.update_layout(
        title="Average Price Profile by Hour of Day (UTC)",
        xaxis=dict(title="Hour (UTC)", tickmode="linear", dtick=2),
        yaxis_title="Avg Price (EUR/MWh)",
        hovermode="x unified",
        height=320,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=70, r=20, t=64, b=40),
    )
    _fig3
    return


@app.cell
def _(filtered_prices, go, pl):
    # Price distribution: box plot per country
    _COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]

    _fig4 = go.Figure()
    for _i, _area in enumerate(sorted(filtered_prices["area"].unique().to_list())):
        _vals = filtered_prices.filter(pl.col("area") == _area)["price_eur_mwh"].to_list()
        _fig4.add_trace(go.Box(
            y=_vals,
            name=_area,
            marker_color=_COLORS[_i % len(_COLORS)],
            boxmean="sd",
            hovertemplate=f"<b>{_area}</b><br>%{{y:,.2f}} EUR/MWh<extra></extra>",
        ))

    _fig4.add_hline(y=0, line_dash="dot", line_color="grey", line_width=1)
    _fig4.update_layout(
        title="Price Distribution by Country",
        yaxis_title="Price (EUR/MWh)",
        height=360,
        margin=dict(l=70, r=20, t=48, b=40),
    )
    _fig4
    return


@app.cell
def _(filtered_prices, mo, pl):
    mo.md("### Raw data"), mo.ui.table(
        filtered_prices
        .with_columns(pl.col("datetime_utc").dt.strftime("%Y-%m-%d %H:%M %Z"))
        .select(["datetime_utc", "area", "price_eur_mwh", "resolution"])
        .sort(["datetime_utc", "area"]),
        page_size=20,
    )
    return


if __name__ == "__main__":
    app.run()
