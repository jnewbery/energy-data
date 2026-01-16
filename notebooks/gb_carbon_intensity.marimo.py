import marimo as mo

app = mo.App(width="medium")


@app.cell
def _():
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt
    from pathlib import Path
    import urllib.request

    return np, pd, plt, Path, urllib


@app.cell
def _(Path, urllib, mo):
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    data_path = data_dir / "gb_carbon_intensity.csv"
    url = (
        "https://api.neso.energy/dataset/"
        "f406810a-1a36-48d2-b542-1dfb1348096e/resource/"
        "0e5fde43-2de7-4fb4-833d-c7bca3b658b0/download/"
        "gb_carbon_intensity.csv"
    )

    if not data_path.exists():
        urllib.request.urlretrieve(url, data_path)
        status = f"Downloaded {data_path} from {url}."
    else:
        status = f"Using existing {data_path}."

    mo.md(status)
    return data_path, url


@app.cell
def _(pd, data_path):
    df = pd.read_csv(data_path, parse_dates=["datetime"])
    df = df.dropna(subset=["actual"]).copy()
    df["month"] = df["datetime"].dt.to_period("M").dt.to_timestamp()
    monthly = (
        df.groupby("month", as_index=False)["actual"]
        .mean()
        .rename(columns={"actual": "average_actual"})
    )
    return df, monthly


@app.cell
def _(mo, monthly):
    mo.md("""## Monthly average carbon intensity""")
    table = mo.ui.dataframe(monthly)
    table
    return table


@app.cell
def _(monthly, pd):
    max_month = monthly["month"].max()
    cutoff = max_month - pd.DateOffset(years=5)
    recent = monthly[monthly["month"] >= cutoff].copy()

    def season_label(month: int) -> str:
        if month in (12, 1, 2):
            return "winter"
        if month in (6, 7, 8):
            return "summer"
        return "spring/autumn"

    recent["season"] = recent["month"].dt.month.map(season_label)
    season_year = recent["month"].dt.year + (recent["month"].dt.month == 12)
    recent["season_year"] = season_year
    seasonal = (
        recent.groupby(["season_year", "season"], as_index=False)["average_actual"]
        .mean()
        .sort_values(["season_year", "season"])
    )
    return cutoff, recent, seasonal


@app.cell
def _(np, pd, seasonal):
    season_month_map = {
        "winter": 1,
        "spring/autumn": 4,
        "summer": 7,
    }

    seasonal = seasonal.copy()
    seasonal["season_date"] = pd.to_datetime(
        {
            "year": seasonal["season_year"],
            "month": seasonal["season"].map(season_month_map),
            "day": 1,
        }
    )

    regression = {}
    for season in seasonal["season"].unique():
        subset = seasonal[seasonal["season"] == season].copy()
        if len(subset) < 2:
            continue
        coeffs = np.polyfit(subset["season_year"], subset["average_actual"], 1)
        subset["predicted"] = np.polyval(coeffs, subset["season_year"])
        regression[season] = subset
    return regression, seasonal


@app.cell
def _(recent, regression, seasonal, plt):
    fig, ax = plt.subplots(figsize=(10, 6))

    ax.plot(
        recent["month"],
        recent["average_actual"],
        color="tab:blue",
        linewidth=1.5,
        label="Monthly average (last 5 years)",
    )

    season_colors = {
        "winter": "tab:purple",
        "spring/autumn": "tab:green",
        "summer": "tab:orange",
    }

    for season, color in season_colors.items():
        subset = seasonal[seasonal["season"] == season]
        ax.plot(
            subset["season_date"],
            subset["average_actual"],
            marker="o",
            linestyle="-",
            color=color,
            label=f"{season.title()} average",
        )
        if season in regression:
            reg = regression[season]
            ax.plot(
                reg["season_date"],
                reg["predicted"],
                linestyle="--",
                color=color,
                alpha=0.7,
                label=f"{season.title()} regression",
            )

    ax.set_title("Grid carbon intensity: monthly and seasonal averages")
    ax.set_xlabel("Month")
    ax.set_ylabel("Carbon intensity (gCO2/kWh)")
    ax.legend(ncol=2)
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig
    return fig


if __name__ == "__main__":
    app.run()
