#!/usr/bin/env python3
"""Fetch Cross-Border Physical Flows (A11) from the ENTSO-E Transparency Platform API.

Usage examples:
    uv run scripts/fetch_entsoe_flows.py --interconnections GB-FR,FR-BE --start 2024-01-01 --end 2024-01-07
    uv run scripts/fetch_entsoe_flows.py  # interactive mode
    ENTSOE_TOKEN=your-token uv run scripts/fetch_entsoe_flows.py --interconnections GB-FR
"""

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

import polars as pl
import requests

BASE_URL = "https://web-api.tp.entsoe.eu/api"

# EIC area codes for common bidding zones / countries
EIC_CODES: dict[str, str] = {
    "GB": "10YGB----------A",
    "FR": "10YFR-RTE------C",
    "BE": "10YBE----------2",
    "NL": "10YNL----------L",
    "DE": "10Y1001A1001A83F",  # Germany (bidding zone aggregate)
    "ES": "10YES-REE------0",
    "PT": "10YPT-REN------W",
    "IT": "10YIT-GRTN-----B",
    "CH": "10YCH-SWISSGRIDZ",
    "AT": "10YAT-APG------L",
    "DK1": "10YDK-1--------W",
    "DK2": "10YDK-2--------M",
    "NO1": "10YNO-1--------2",
    "NO2": "10YNO-2--------T",
    "SE1": "10Y1001A1001A44P",
    "SE2": "10Y1001A1001A45N",
    "SE3": "10Y1001A1001A46L",
    "SE4": "10Y1001A1001A47J",
    "FI": "10YFI-1--------U",
    "PL": "10YPL-AREA-----S",
    "CZ": "10YCZ-CEPS-----N",
    "SK": "10YSK-SEPS-----K",
    "HU": "10YHU-MAVIR----U",
    "RO": "10YRO-TEL------P",
    "HR": "10YHR-HEP------M",
    "SI": "10YSI-ELES-----O",
    "RS": "10YCS-SERBIATSOV",
    "GR": "10YGR-HTSO-----Y",
    "BG": "10YCA-BULGARIA-R",
}

# Well-known cross-border interconnections (out_country, in_country)
COMMON_INTERCONNECTIONS: list[tuple[str, str]] = [
    ("GB", "FR"),
    ("GB", "BE"),
    ("GB", "NL"),
    ("FR", "BE"),
    ("FR", "DE"),
    ("FR", "ES"),
    ("FR", "IT"),
    ("FR", "CH"),
    ("DE", "AT"),
    ("DE", "CH"),
    ("DE", "NL"),
    ("DE", "BE"),
    ("DE", "PL"),
    ("DE", "CZ"),
    ("NL", "BE"),
    ("NO1", "SE3"),
    ("NO2", "DK1"),
    ("DK1", "SE3"),
    ("DK2", "SE4"),
    ("FI", "SE1"),
]


def get_token(args_token: str | None) -> str:
    token = args_token or os.environ.get("ENTSOE_TOKEN") or os.environ.get("ENTSOE_SECURITY_TOKEN")
    if not token:
        print("No ENTSO-E security token found.")
        print("Set ENTSOE_TOKEN environment variable, or pass --token.")
        token = input("Enter your ENTSO-E security token: ").strip()
    if not token:
        print("Error: a security token is required.", file=sys.stderr)
        sys.exit(1)
    return token


def parse_interconnections(spec: str) -> list[tuple[str, str]]:
    """Parse 'GB-FR,FR-DE' into [('GB','FR'), ('FR','DE')]."""
    pairs = []
    for part in spec.upper().split(","):
        part = part.strip()
        if "-" not in part:
            print(f"Warning: skipping malformed interconnection '{part}' (expected format: GB-FR)", file=sys.stderr)
            continue
        # Handle EIC codes that contain hyphens: split on first hyphen only if both parts are short country codes
        # Use last hyphen if the format looks like an EIC code, first hyphen otherwise
        # Strategy: try splitting on first '-'
        left, _, right = part.partition("-")
        if not right:
            print(f"Warning: skipping malformed interconnection '{part}'", file=sys.stderr)
            continue
        # If right side contains '-', it might be a multi-char code like NO1-SE3 → split was wrong
        # Re-split: find the pair separator as the hyphen that separates two valid country codes
        # Simple heuristic: try the first hyphen; if left isn't in EIC_CODES, try the second
        if left not in EIC_CODES:
            # Try known codes via prefix matching
            matched = False
            for code in EIC_CODES:
                if part.startswith(code + "-"):
                    out_c = code
                    in_c = part[len(code) + 1:]
                    if in_c in EIC_CODES:
                        pairs.append((out_c, in_c))
                        matched = True
                        break
            if not matched:
                print(f"Warning: unknown country code in '{part}'. Known codes: {', '.join(sorted(EIC_CODES))}", file=sys.stderr)
        else:
            in_c = right
            if in_c not in EIC_CODES:
                print(f"Warning: unknown country code '{in_c}'. Known codes: {', '.join(sorted(EIC_CODES))}", file=sys.stderr)
            else:
                pairs.append((left, in_c))
    return pairs


def select_interconnections_interactive() -> list[tuple[str, str]]:
    print("\nCommon interconnections:")
    for i, (out_c, in_c) in enumerate(COMMON_INTERCONNECTIONS, 1):
        print(f"  {i:2}. {out_c}-{in_c}")
    print()
    print("Enter interconnections as comma-separated pairs (e.g. GB-FR,FR-DE)")
    print("or enter numbers from the list above (e.g. 1,3,5)")
    raw = input("Interconnections: ").strip()
    if not raw:
        print("No interconnections specified.", file=sys.stderr)
        sys.exit(1)

    # Check if user entered numbers
    parts = [p.strip() for p in raw.split(",")]
    if all(p.isdigit() for p in parts):
        result = []
        for p in parts:
            idx = int(p) - 1
            if 0 <= idx < len(COMMON_INTERCONNECTIONS):
                result.append(COMMON_INTERCONNECTIONS[idx])
            else:
                print(f"Warning: index {p} out of range, skipping.", file=sys.stderr)
        return result
    else:
        return parse_interconnections(raw)


def format_period(dt: date) -> str:
    """Format a date as YYYYMMDD0000 for the ENTSO-E API (midnight UTC)."""
    return dt.strftime("%Y%m%d0000")


def fetch_flows(
    token: str,
    out_domain: str,
    in_domain: str,
    period_start: str,
    period_end: str,
) -> ET.Element | None:
    params = {
        "documentType": "A11",
        "out_Domain": out_domain,
        "in_Domain": in_domain,
        "periodStart": period_start,
        "periodEnd": period_end,
        "securityToken": token,
    }
    resp = requests.get(BASE_URL, params=params, timeout=60)
    if resp.status_code != 200:
        print(f"  HTTP {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
        return None

    root = ET.fromstring(resp.text)
    ns_match = root.tag.rstrip(">").split("{")
    if len(ns_match) > 1 and "Acknowledgement" in root.tag:
        # Error response
        ns = "{" + ns_match[1] + "}"
        reason = root.find(f".//{ns}Reason")
        if reason is not None:
            code_el = reason.find(f"{ns}code")
            text_el = reason.find(f"{ns}text")
            code = code_el.text if code_el is not None else "?"
            text = text_el.text if text_el is not None else "?"
            print(f"  API error [{code}]: {text}", file=sys.stderr)
        return None
    return root


def resolution_to_minutes(resolution: str) -> int:
    """Convert ISO 8601 duration like PT15M, PT30M, PT60M, P1Y to minutes."""
    resolution = resolution.strip()
    if resolution.startswith("PT") and resolution.endswith("M"):
        return int(resolution[2:-1])
    if resolution.startswith("PT") and resolution.endswith("H"):
        return int(resolution[2:-1]) * 60
    if resolution == "P1Y":
        return 525600  # approximate
    return 60  # default


def parse_flows_xml(
    root: ET.Element,
    out_country: str,
    in_country: str,
    out_domain: str,
    in_domain: str,
) -> list[dict]:
    ns_raw = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""
    ns = f"{{{ns_raw}}}" if ns_raw else ""

    rows = []
    for ts in root.findall(f".//{ns}TimeSeries"):
        for period in ts.findall(f".//{ns}Period"):
            start_el = period.find(f"{ns}timeInterval/{ns}start")
            resolution_el = period.find(f"{ns}resolution")
            if start_el is None or resolution_el is None:
                continue

            start_str = start_el.text.strip()  # e.g. "2023-08-23T22:00Z"
            try:
                start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            except ValueError:
                continue

            resolution = resolution_el.text.strip()
            interval_minutes = resolution_to_minutes(resolution)

            for point in period.findall(f"{ns}Point"):
                pos_el = point.find(f"{ns}position")
                qty_el = point.find(f"{ns}quantity")
                if pos_el is None or qty_el is None:
                    continue
                position = int(pos_el.text)
                quantity = float(qty_el.text)
                point_dt = start_dt + timedelta(minutes=(position - 1) * interval_minutes)
                rows.append(
                    {
                        "datetime_utc": point_dt.isoformat(),
                        "out_domain": out_domain,
                        "in_domain": in_domain,
                        "out_country": out_country,
                        "in_country": in_country,
                        "flow_mw": quantity,
                        "resolution": resolution,
                    }
                )
    return rows


def save_csv(rows: list[dict], out_country: str, in_country: str, start: date, end: date) -> str:
    filename = f"cross_border_flows_{out_country}_{in_country}_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.csv"
    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)
    df = pl.DataFrame(rows)
    df = df.sort("datetime_utc")
    df.write_csv(filepath)
    return filepath


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch ENTSO-E Cross-Border Physical Flows (A11) and save as CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--token",
        help="ENTSO-E security token (overrides ENTSOE_TOKEN env var)",
    )
    parser.add_argument(
        "--interconnections",
        help="Comma-separated list of interconnections, e.g. GB-FR,FR-DE",
    )
    parser.add_argument(
        "--start",
        help="Start date (YYYY-MM-DD, UTC). Defaults to 7 days ago.",
    )
    parser.add_argument(
        "--end",
        help="End date (YYYY-MM-DD, UTC). Defaults to today.",
    )
    args = parser.parse_args()

    token = get_token(args.token)

    # Resolve interconnections
    if args.interconnections:
        interconnections = parse_interconnections(args.interconnections)
    else:
        interconnections = select_interconnections_interactive()

    if not interconnections:
        print("No valid interconnections specified.", file=sys.stderr)
        sys.exit(1)

    # Resolve date range
    today = date.today()
    if args.end:
        end_date = date.fromisoformat(args.end)
    else:
        end_date = today

    if args.start:
        start_date = date.fromisoformat(args.start)
    else:
        start_date = end_date - timedelta(days=7)

    if (end_date - start_date).days > 365:
        print("Warning: date range exceeds 365 days. The ENTSO-E API may return partial results.", file=sys.stderr)

    period_start = format_period(start_date)
    period_end = format_period(end_date + timedelta(days=1))  # end is exclusive in API

    print(f"\nFetching flows from {start_date} to {end_date} (UTC)")
    print(f"Interconnections: {', '.join(f'{o}-{i}' for o, i in interconnections)}\n")

    for out_country, in_country in interconnections:
        out_domain = EIC_CODES[out_country]
        in_domain = EIC_CODES[in_country]
        print(f"  Fetching {out_country} → {in_country} ({out_domain} → {in_domain})...", end=" ", flush=True)

        root = fetch_flows(token, out_domain, in_domain, period_start, period_end)
        if root is None:
            print("FAILED")
            continue

        rows = parse_flows_xml(root, out_country, in_country, out_domain, in_domain)
        if not rows:
            print("no data returned")
            continue

        filepath = save_csv(rows, out_country, in_country, start_date, end_date)
        print(f"saved {len(rows)} rows → {filepath}")

    print("\nDone.")


if __name__ == "__main__":
    main()
