#!/usr/bin/env python3
"""Aggregate cross-border flows and total load into per-country summary CSVs.

Reads all cross_border_flows_*.csv and total_load_*.csv files from the data/
directory and writes one CSV per country containing daily total imports,
exports, load, and derived percentage columns.

Usage:
    uv run scripts/export_country_balance.py
    uv run scripts/export_country_balance.py --countries CZ,HU,SK
    uv run scripts/export_country_balance.py --data-dir path/to/data --out-dir path/to/output
    uv run scripts/export_country_balance.py --resolution daily   # daily (default), monthly, or yearly
"""

import argparse
import glob
import sys
from pathlib import Path

import polars as pl


def load_flows(data_dir: Path, countries: set[str]) -> pl.DataFrame:
    files = sorted(glob.glob(str(data_dir / "cross_border_flows_*.csv")))
    frames = []
    for f in files:
        try:
            df = pl.read_csv(f)
            if {"out_country", "in_country", "flow_mw"}.issubset(set(df.columns)):
                rel = df.filter(
                    pl.col("out_country").is_in(countries) |
                    pl.col("in_country").is_in(countries)
                )
                if rel.height > 0:
                    frames.append(rel)
        except Exception as e:
            print(f"  Warning: skipping {f}: {e}", file=sys.stderr)

    if not frames:
        return pl.DataFrame()

    return (
        pl.concat(frames, how="diagonal_relaxed")
        .with_columns(
            pl.col("datetime_utc").str.to_datetime(
                format="%Y-%m-%dT%H:%M:%S%z", time_unit="us"
            )
        )
        .unique(subset=["datetime_utc", "out_country", "in_country"], keep="first")
        .sort(["out_country", "in_country", "datetime_utc"])
    )


def load_total_load(data_dir: Path, countries: set[str]) -> pl.DataFrame | None:
    files = sorted(glob.glob(str(data_dir / "total_load_*.csv")))
    frames = []
    for f in files:
        try:
            df = pl.read_csv(f)
            if "area" in df.columns:
                rel = df.filter(pl.col("area").is_in(countries))
                if rel.height > 0:
                    frames.append(rel)
        except Exception as e:
            print(f"  Warning: skipping {f}: {e}", file=sys.stderr)

    if not frames:
        return None

    return (
        pl.concat(frames, how="diagonal_relaxed")
        .with_columns(
            pl.col("datetime_utc").str.to_datetime(
                format="%Y-%m-%dT%H:%M:%S%z", time_unit="us"
            )
        )
        .unique(subset=["datetime_utc", "area"], keep="first")
        .sort(["area", "datetime_utc"])
    )


def build_balance(
    flows: pl.DataFrame,
    load: pl.DataFrame | None,
    countries: list[str],
    resolution: str,
) -> dict[str, pl.DataFrame]:
    """Return a dict of country -> summary DataFrame at the requested resolution."""

    every = {"daily": "1d", "monthly": "1mo", "yearly": "1y"}[resolution]

    # Step 1: aggregate each interconnection to the target resolution (handles
    # mixed PT15M/PT60M by taking the mean MW, then summing across borders).
    daily_links = (
        flows
        .filter(
            pl.col("out_country").is_in(countries) |
            pl.col("in_country").is_in(countries)
        )
        .sort(["out_country", "in_country", "datetime_utc"])
        .group_by_dynamic(
            "datetime_utc", every=every,
            group_by=["out_country", "in_country"],
        )
        .agg(pl.col("flow_mw").mean())
    )

    # Step 2: total imports per country (sum across all exporting neighbours)
    imports = (
        daily_links
        .filter(pl.col("in_country").is_in(countries))
        .group_by(["datetime_utc", "in_country"])
        .agg(pl.col("flow_mw").sum().alias("import_mw"))
        .rename({"in_country": "country"})
    )

    # Step 3: total exports per country (sum across all importing neighbours)
    exports = (
        daily_links
        .filter(pl.col("out_country").is_in(countries))
        .group_by(["datetime_utc", "out_country"])
        .agg(pl.col("flow_mw").sum().alias("export_mw"))
        .rename({"out_country": "country"})
    )

    balance = (
        imports
        .join(exports, on=["datetime_utc", "country"], how="full", coalesce=True)
        .sort(["country", "datetime_utc"])
    )

    # Step 4: join load
    if load is not None:
        load_agg = (
            load
            .filter(pl.col("area").is_in(countries))
            .sort(["area", "datetime_utc"])
            .group_by_dynamic("datetime_utc", every=every, group_by="area")
            .agg(pl.col("load_mw").mean())
            .rename({"area": "country"})
        )
        balance = (
            balance
            .join(load_agg, on=["datetime_utc", "country"], how="left")
        )
    else:
        balance = balance.with_columns(pl.lit(None).cast(pl.Float64).alias("load_mw"))

    balance = balance.with_columns([
        (pl.col("import_mw") - pl.col("export_mw")).alias("net_import_mw"),
        (pl.col("import_mw") / pl.col("load_mw") * 100).alias("import_pct_of_load"),
        (pl.col("export_mw") / pl.col("load_mw") * 100).alias("export_pct_of_load"),
        (
            (pl.col("import_mw") - pl.col("export_mw")) /
            pl.col("load_mw") * 100
        ).alias("net_import_pct_of_load"),
    ])

    # Split into per-country DataFrames
    result = {}
    for country in countries:
        df = (
            balance
            .filter(pl.col("country") == country)
            .drop("country")
            .sort("datetime_utc")
            .with_columns(
                pl.col("datetime_utc").dt.strftime("%Y-%m-%d").alias("date")
                if resolution == "daily"
                else pl.col("datetime_utc").dt.strftime("%Y-%m").alias("date")
                if resolution == "monthly"
                else pl.col("datetime_utc").dt.strftime("%Y").alias("date")
            )
            .select([
                "date",
                "import_mw",
                "export_mw",
                "net_import_mw",
                "load_mw",
                "import_pct_of_load",
                "export_pct_of_load",
                "net_import_pct_of_load",
            ])
        )
        result[country] = df

    return result


def main() -> None:
    repo_root = Path(__file__).parent.parent
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--countries", default="CZ,HU,SK",
        help="Comma-separated country codes (default: CZ,HU,SK)",
    )
    parser.add_argument(
        "--data-dir", default=str(repo_root / "data"),
        help="Directory containing the CSV source files",
    )
    parser.add_argument(
        "--out-dir", default=str(repo_root / "data"),
        help="Directory to write output CSVs (default: same as data-dir)",
    )
    parser.add_argument(
        "--resolution", choices=["daily", "monthly", "yearly"], default="daily",
        help="Time resolution of the output (default: daily)",
    )
    args = parser.parse_args()

    countries_list = [c.strip().upper() for c in args.countries.split(",")]
    countries_set = set(countries_list)
    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Countries : {', '.join(countries_list)}")
    print(f"Resolution: {args.resolution}")
    print(f"Data dir  : {data_dir}")
    print(f"Output dir: {out_dir}")
    print()

    print("Loading cross-border flow files...")
    flows = load_flows(data_dir, countries_set)
    if flows.is_empty():
        print("No flow data found — aborting.", file=sys.stderr)
        sys.exit(1)
    print(f"  {flows.height:,} rows loaded")

    print("Loading total load files...")
    load = load_total_load(data_dir, countries_set)
    if load is not None:
        available = sorted(load["area"].unique().to_list())
        print(f"  {load.height:,} rows loaded (countries with load data: {', '.join(available)})")
        missing = sorted(countries_set - set(available))
        if missing:
            print(f"  Note: no load data for {', '.join(missing)} — load/% columns will be empty")
    else:
        print("  No load data found — load/% columns will be empty")

    print("\nAggregating...")
    per_country = build_balance(flows, load, countries_list, args.resolution)

    for country, df in per_country.items():
        out_path = out_dir / f"balance_{country}_{args.resolution}.csv"
        df.write_csv(out_path)
        rows = df.height
        has_load = df["load_mw"].drop_nulls().len() > 0
        print(f"  {out_path.name}  ({rows} rows, load data: {'yes' if has_load else 'no'})")

    print("\nDone.")


if __name__ == "__main__":
    main()
