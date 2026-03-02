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
from datetime import date, datetime, timedelta

import polars as pl
import requests

BASE_URL = "https://web-api.tp.entsoe.eu/api"

# EIC area codes sourced from the ENTSO-E Transparency Platform API documentation
# and the entsoe-py open-source library (https://github.com/EnergieID/entsoe-py).
# Each entry: short name -> (EIC code, human-readable description)
# Note: DE_AT_LU (pre-Oct 2018) and DE_LU (post-Oct 2018) are separate historical BZs.
EIC_CODES: dict[str, tuple[str, str]] = {
    "AL":        ("10YAL-KESH-----5", "Albania"),
    "AT":        ("10YAT-APG------L", "Austria"),
    "BA":        ("10YBA-JPCC-----D", "Bosnia Herzegovina"),
    "BE":        ("10YBE----------2", "Belgium"),
    "BG":        ("10YCA-BULGARIA-R", "Bulgaria"),
    "BY":        ("10Y1001A1001A51S", "Belarus"),
    "CH":        ("10YCH-SWISSGRIDZ", "Switzerland"),
    "CZ":        ("10YCZ-CEPS-----N", "Czech Republic"),
    "DE_AT_LU":  ("10Y1001A1001A63L", "DE-AT-LU BZ (pre-Oct 2018)"),
    "DE_LU":     ("10Y1001A1001A82H", "Germany-Luxembourg (post-Oct 2018)"),
    "DK_1":      ("10YDK-1--------W", "Denmark DK1"),
    "DK_2":      ("10YDK-2--------M", "Denmark DK2"),
    "EE":        ("10Y1001A1001A39I", "Estonia"),
    "ES":        ("10YES-REE------0", "Spain"),
    "FI":        ("10YFI-1--------U", "Finland"),
    "FR":        ("10YFR-RTE------C", "France"),
    "GB":        ("10YGB----------A", "Great Britain"),
    "GR":        ("10YGR-HTSO-----Y", "Greece"),
    "HR":        ("10YHR-HEP------M", "Croatia"),
    "HU":        ("10YHU-MAVIR----U", "Hungary"),
    "IE":        ("10YIE-1001A00010", "Ireland (EirGrid CA)"),
    "IE_SEM":    ("10Y1001A1001A59C", "Ireland SEM BZ"),
    "IT_BRNN":   ("10Y1001A1001A699", "Italy-Brindisi"),
    "IT_CALA":   ("10Y1001C--00096J", "Italy-Calabria"),
    "IT_CNOR":   ("10Y1001A1001A70O", "Italy-Centre-North"),
    "IT_CSUD":   ("10Y1001A1001A71M", "Italy-Centre-South"),
    "IT_FOGN":   ("10Y1001A1001A72K", "Italy-Foggia"),
    "IT_GR":     ("10Y1001A1001A66F", "Italy-Greece BZ"),
    "IT_NORD":   ("10Y1001A1001A73I", "Italy-North"),
    "IT_NORD_AT":("10Y1001A1001A80L", "Italy-North-AT BZ"),
    "IT_NORD_CH":("10Y1001A1001A68B", "Italy-North-CH BZ"),
    "IT_NORD_FR":("10Y1001A1001A81J", "Italy-North-FR BZ"),
    "IT_ROSN":   ("10Y1001A1001A77A", "Italy-Rossano"),
    "IT_SARD":   ("10Y1001A1001A74G", "Italy-Sardinia"),
    "IT_SICI":   ("10Y1001A1001A75E", "Italy-Sicily"),
    "IT_SUD":    ("10Y1001A1001A788", "Italy-South"),
    "LT":        ("10YLT-1001A0008Q", "Lithuania"),
    "LV":        ("10YLV-1001A00074", "Latvia"),
    "ME":        ("10YCS-CG-TSO---S", "Montenegro"),
    "MK":        ("10YMK-MEPSO----8", "North Macedonia"),
    "MT":        ("10Y1001A1001A93C", "Malta"),
    "NIE":       ("10Y1001A1001A016", "Northern Ireland"),
    "NL":        ("10YNL----------L", "Netherlands"),
    "NO_1":      ("10YNO-1--------2", "Norway NO1"),
    "NO_2":      ("10YNO-2--------T", "Norway NO2"),
    "NO_3":      ("10YNO-3--------J", "Norway NO3"),
    "NO_4":      ("10YNO-4--------9", "Norway NO4"),
    "NO_5":      ("10Y1001A1001A48H", "Norway NO5"),
    "PL":        ("10YPL-AREA-----S", "Poland"),
    "PT":        ("10YPT-REN------W", "Portugal"),
    "RO":        ("10YRO-TEL------P", "Romania"),
    "RS":        ("10YCS-SERBIATSOV", "Serbia"),
    "RU":        ("10Y1001A1001A49F", "Russia"),
    "RU_KGD":    ("10Y1001A1001A50U", "Russia-Kaliningrad"),
    "SE_1":      ("10Y1001A1001A44P", "Sweden SE1"),
    "SE_2":      ("10Y1001A1001A45N", "Sweden SE2"),
    "SE_3":      ("10Y1001A1001A46L", "Sweden SE3"),
    "SE_4":      ("10Y1001A1001A47J", "Sweden SE4"),
    "SI":        ("10YSI-ELES-----O", "Slovenia"),
    "SK":        ("10YSK-SEPS-----K", "Slovakia"),
    "TR":        ("10YTR-TEIAS----W", "Turkey"),
    "UA":        ("10Y1001C--00003F", "Ukraine"),
    "XK":        ("10Y1001C--00100H", "Kosovo"),
}

# Comprehensive list of known physical interconnections, sourced from the
# ENTSO-E Transparency Platform documentation and the entsoe-py library
# NEIGHBOURS mapping (https://github.com/EnergieID/entsoe-py).
# These are all directed (A→B) pairs; both directions are valid queries.
_NEIGHBOURS: dict[str, list[str]] = {
    "AL":       ["ME", "MK", "GR", "RS"],
    "AT":       ["CH", "CZ", "DE_LU", "HU", "IT_NORD", "SI"],
    "BA":       ["HR", "ME", "RS"],
    "BE":       ["NL", "DE_AT_LU", "FR", "GB", "DE_LU"],
    "BG":       ["GR", "MK", "RO", "RS", "TR"],
    "BY":       ["LT", "LV", "UA"],
    "CH":       ["AT", "DE_AT_LU", "DE_LU", "FR", "IT_NORD", "IT_NORD_CH"],
    "CZ":       ["AT", "DE_AT_LU", "DE_LU", "PL", "SK"],
    "DE_AT_LU": ["BE", "CH", "CZ", "DK_1", "DK_2", "FR", "IT_NORD", "IT_NORD_AT", "NL", "PL", "SE_4", "SI"],
    "DE_LU":    ["AT", "BE", "CH", "CZ", "DK_1", "DK_2", "FR", "NO_2", "NL", "PL", "SE_4"],
    "DK_1":     ["DE_AT_LU", "DE_LU", "DK_2", "NO_2", "SE_3", "NL", "GB"],
    "DK_2":     ["DE_AT_LU", "DE_LU", "DK_1", "SE_4"],
    "EE":       ["FI", "LV", "RU"],
    "ES":       ["FR", "PT"],
    "FI":       ["EE", "NO_4", "RU", "SE_1", "SE_3"],
    "FR":       ["BE", "CH", "DE_AT_LU", "DE_LU", "ES", "GB", "IT_NORD", "IT_NORD_FR"],
    "GB":       ["BE", "FR", "IE_SEM", "NL", "NO_2", "DK_1"],
    "GR":       ["AL", "BG", "IT_BRNN", "IT_GR", "MK", "TR"],
    "HR":       ["BA", "HU", "RS", "SI"],
    "HU":       ["AT", "HR", "RO", "RS", "SI", "SK", "UA"],
    "IE":       ["GB", "NIE"],
    "IE_SEM":   ["GB"],
    "IT_BRNN":  ["GR", "IT_SUD"],
    "IT_CALA":  ["IT_SICI", "IT_SUD"],
    "IT_CNOR":  ["IT_NORD", "IT_CSUD", "IT_SARD"],
    "IT_CSUD":  ["IT_CNOR", "IT_SARD", "IT_SUD"],
    "IT_FOGN":  ["IT_SUD"],
    "IT_NORD":  ["CH", "DE_AT_LU", "FR", "SI", "AT", "IT_CNOR"],
    "IT_ROSN":  ["IT_SICI", "IT_SUD"],
    "IT_SARD":  ["IT_CNOR", "IT_CSUD"],
    "IT_SICI":  ["IT_CALA", "IT_ROSN", "MT"],
    "IT_SUD":   ["IT_BRNN", "IT_CSUD", "IT_FOGN", "IT_ROSN", "IT_CALA"],
    "LT":       ["BY", "LV", "PL", "RU_KGD", "SE_4"],
    "LV":       ["EE", "LT", "RU"],
    "ME":       ["AL", "BA", "RS"],
    "MK":       ["BG", "GR", "RS"],
    "MT":       ["IT_SICI"],
    "NIE":      ["GB", "IE"],
    "NL":       ["BE", "DE_AT_LU", "DE_LU", "GB", "NO_2", "DK_1"],
    "NO_1":     ["NO_2", "NO_3", "NO_5", "SE_3"],
    "NO_2":     ["DE_LU", "DK_1", "NL", "NO_1", "NO_5", "GB"],
    "NO_3":     ["NO_1", "NO_4", "NO_5", "SE_2"],
    "NO_4":     ["SE_2", "FI", "NO_3", "SE_1"],
    "NO_5":     ["NO_1", "NO_2", "NO_3"],
    "PL":       ["CZ", "DE_AT_LU", "DE_LU", "LT", "SE_4", "SK", "UA"],
    "PT":       ["ES"],
    "RO":       ["BG", "HU", "RS", "UA"],
    "RS":       ["AL", "BA", "BG", "HR", "HU", "ME", "MK", "RO"],
    "SE_1":     ["FI", "NO_4", "SE_2"],
    "SE_2":     ["NO_3", "NO_4", "SE_1", "SE_3"],
    "SE_3":     ["DK_1", "FI", "NO_1", "SE_2", "SE_4"],
    "SE_4":     ["DE_AT_LU", "DE_LU", "DK_2", "LT", "PL", "SE_3"],
    "SI":       ["AT", "DE_AT_LU", "HR", "IT_NORD", "HU"],
    "SK":       ["CZ", "HU", "PL", "UA"],
    "TR":       ["BG", "GR"],
    "UA":       ["BY", "HU", "PL", "RO", "SK"],
}

# Derive the canonical ordered list of all unique undirected interconnections
_seen: set[tuple[str, str]] = set()
ALL_INTERCONNECTIONS: list[tuple[str, str]] = []
for _out, _ins in sorted(_NEIGHBOURS.items()):
    for _in in _ins:
        pair = tuple(sorted([_out, _in]))
        if pair not in _seen:
            _seen.add(pair)
            ALL_INTERCONNECTIONS.append((_out, _in))


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
    """Parse 'GB-FR,SE_3-DK_1' into [('GB','FR'), ('SE_3','DK_1')]."""
    pairs = []
    known = set(EIC_CODES.keys())
    for part in spec.upper().split(","):
        part = part.strip()
        # Try splitting at each hyphen to find a valid (out, in) pair
        matched = False
        for i in range(1, len(part)):
            if part[i] == "-":
                out_c = part[:i]
                in_c = part[i + 1:]
                if out_c in known and in_c in known:
                    pairs.append((out_c, in_c))
                    matched = True
                    break
        if not matched:
            print(f"Warning: could not parse '{part}'. Known area codes: {', '.join(sorted(known))}", file=sys.stderr)
    return pairs


def select_interconnections_interactive() -> list[tuple[str, str]]:
    print(f"\nAll known ENTSO-E cross-border interconnections ({len(ALL_INTERCONNECTIONS)} total).")
    print("You can filter by typing a country/area code prefix (e.g. 'GB', 'NO', 'IT').")
    print("Or press Enter to see all.\n")
    filter_str = input("Filter (optional): ").strip().upper()

    filtered = [
        (o, i) for o, i in ALL_INTERCONNECTIONS
        if not filter_str or filter_str in o or filter_str in i
    ]

    if not filtered:
        print(f"No interconnections match '{filter_str}'.", file=sys.stderr)
        sys.exit(1)

    print()
    for idx, (out_c, in_c) in enumerate(filtered, 1):
        out_desc = EIC_CODES[out_c][1] if out_c in EIC_CODES else out_c
        in_desc = EIC_CODES[in_c][1] if in_c in EIC_CODES else in_c
        print(f"  {idx:3}. {out_c:<12} → {in_c:<12}  ({out_desc} → {in_desc})")

    print()
    print("Enter numbers (e.g. 1,3,5) or free-form pairs (e.g. GB-FR,FR-DE), or both:")
    raw = input("Selection: ").strip()
    if not raw:
        print("No interconnections selected.", file=sys.stderr)
        sys.exit(1)

    result: list[tuple[str, str]] = []
    for token in raw.split(","):
        token = token.strip()
        if token.isdigit():
            idx = int(token) - 1
            if 0 <= idx < len(filtered):
                result.append(filtered[idx])
            else:
                print(f"Warning: index {token} out of range, skipping.", file=sys.stderr)
        else:
            result.extend(parse_interconnections(token))
    return result


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
        out_domain = EIC_CODES[out_country][0]
        in_domain = EIC_CODES[in_country][0]
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
