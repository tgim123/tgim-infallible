#!/usr/bin/env python3
"""
TGIM MACRO/MICRO 45-PAIR BATCH RUNNER v3.2
=========================================

Runs the existing TGIM Macro/Micro Sweeper v3.2 sequentially across the
remaining OANDA FX universe, saving one isolated result folder per pair plus a
batch-wide champion leaderboard and promotion bank.

Default behavior
----------------
- Skips EUR_USD and AUD_USD because they are existing manual/reference controls.
- Runs the remaining 45 pairs in leverage-tier order (50:1 -> 33.3:1 -> 20:1).
- Continues to the next pair if one instrument fails.
- Reuses the shared candle cache during the same Render run.
- Creates a separate stdout log and result directory for every pair.
- Reads each pair's PAIR_PROFILE_PROMOTION.json when finished.
- Writes batch progress after every pair so the run is auditable while active.
- Supports --pairs for a custom subset and --start-at for manual resume.

This runner does not change the trading logic.  It orchestrates the existing
v3.2 pair sweeper exactly once per requested instrument.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

BATCH_BUILD_ID = "TGIM-MACRO-MICRO-BATCH-V3.2-20260830"
EXPECTED_SWEEPER_BUILD = "TGIM-MACRO-MICRO-V3.2-20260829"

# User's OANDA research universe. EUR_USD and AUD_USD are intentionally omitted
# from DEFAULT_45 because they are existing reference/manual champions.
TIER_50 = [
    "EUR_USD", "USD_CAD", "EUR_CAD", "USD_DKK",
]

TIER_33 = [
    "AUD_CHF", "AUD_USD", "EUR_NZD", "NZD_USD", "EUR_CHF", "NZD_CAD",
    "AUD_CAD", "NZD_CHF", "USD_SEK", "EUR_AUD", "USD_CHF", "AUD_NZD",
    "CAD_CHF", "EUR_SEK",
]

TIER_20 = [
    "SGD_JPY", "EUR_GBP", "USD_HUF", "GBP_CHF", "USD_THB", "CAD_JPY",
    "USD_CNH", "USD_PLN", "GBP_AUD", "AUD_JPY", "EUR_PLN", "EUR_HUF",
    "USD_JPY", "GBP_NZD", "GBP_CAD", "AUD_SGD", "GBP_JPY", "GBP_USD",
    "USD_CZK", "EUR_CZK", "GBP_PLN", "GBP_SGD", "EUR_SGD", "EUR_JPY",
    "CAD_SGD", "NZD_JPY", "CHF_JPY", "NZD_SGD", "USD_SGD",
]

REFERENCE_PAIRS = {"EUR_USD", "AUD_USD"}
DEFAULT_45 = [p for p in (TIER_50 + TIER_33 + TIER_20) if p not in REFERENCE_PAIRS]

TIER_BY_PAIR = {p: "50:1" for p in TIER_50}
TIER_BY_PAIR.update({p: "33.3:1" for p in TIER_33})
TIER_BY_PAIR.update({p: "20:1" for p in TIER_20})


def norm_pair(raw: str) -> str:
    s = raw.strip().upper().replace("OANDA:", "").replace("/", "_").replace("-", "_")
    if "_" not in s and len(s) == 6:
        s = s[:3] + "_" + s[3:]
    if len(s) != 7 or s[3] != "_":
        raise argparse.ArgumentTypeError(f"Bad pair: {raw!r}")
    return s


def parse_pairs(text: str) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        p = norm_pair(item)
        if p not in seen:
            out.append(p)
            seen.add(p)
    return out


def parse_args() -> argparse.Namespace:
    here = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(description="TGIM v3.2 sequential Macro/Micro multi-pair runner")
    p.add_argument("--sweeper", default=str(here / "tgim_joint_4rail_sweeper_v1.py"),
                   help="Path to the v3.2 single-pair sweeper")
    p.add_argument("--pairs", default="",
                   help="Comma-separated override list. Default = remaining 45 pairs.")
    p.add_argument("--include-references", action="store_true",
                   help="Include EUR_USD and AUD_USD ahead of the remaining universe.")
    p.add_argument("--start-at", default="",
                   help="Start at this pair within the selected list; useful for manual resume.")
    p.add_argument("--max-pairs", type=int, default=0,
                   help="Optional cap for a test run; 0 means all selected pairs.")
    p.add_argument("--result-root", default="batch_results",
                   help="Root folder for this batch's pair result directories and summaries.")
    p.add_argument("--cache-dir", default="./cache",
                   help="Shared candle cache passed to every pair sweep.")
    p.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True,
                   help="Skip a pair if its promotion JSON already exists in this batch folder.")
    p.add_argument("--stop-on-error", action="store_true",
                   help="Stop batch after first failed pair. Default continues.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print pair sequence and commands without executing sweeps.")

    # Core single-pair sweeper args passed through unchanged.
    p.add_argument("--env", choices=["practice", "live"], default=os.getenv("OANDA_ENV", "practice"))
    p.add_argument("--token", default=os.getenv("OANDA_TOKEN", ""))
    p.add_argument("--eval-days", type=int, default=120)
    p.add_argument("--forward-days", type=int, default=30)
    p.add_argument("--warmup-days", type=int, default=90)
    p.add_argument("--registry-limit", type=int, default=27)
    p.add_argument("--seed", choices=["both", "AUD51", "EUR47"], default="both")
    p.add_argument("--expanded-scope", choices=["active", "all10"], default="all10")
    p.add_argument("--macro-top-per-seed", type=int, default=50)
    p.add_argument("--bridge-top-per-seed", type=int, default=10)
    p.add_argument("--skip-bridge", action="store_true")
    p.add_argument("--skip-fourth", action="store_true")
    p.add_argument("--refresh", action="store_true")
    return p.parse_args()


def pair_sequence(args: argparse.Namespace) -> List[str]:
    if args.pairs:
        seq = parse_pairs(args.pairs)
    else:
        seq = list(DEFAULT_45)
        if args.include_references:
            seq = ["EUR_USD", "AUD_USD"] + seq

    if args.start_at:
        start = norm_pair(args.start_at)
        if start not in seq:
            raise SystemExit(f"--start-at {start} is not in the selected pair list")
        seq = seq[seq.index(start):]

    if args.max_pairs > 0:
        seq = seq[:args.max_pairs]
    return seq


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_float(v, default=0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def safe_int(v, default=0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def promotion_row(pair: str, promo: dict, pair_dir: Path, elapsed: float) -> dict:
    m = promo.get("metrics", {})
    return {
        "pair": pair,
        "tier": TIER_BY_PAIR.get(pair, "custom"),
        "status": "DONE",
        "seed_math": promo.get("seed_math_profile", ""),
        "guardian": promo.get("guardian_source", ""),
        "trigger": promo.get("trigger_source", ""),
        "macro": promo.get("macro_route", ""),
        "micro": promo.get("micro_route", ""),
        "bridge": promo.get("bridge_rail", ""),
        "fourth": promo.get("fourth_rail", ""),
        "route_count": safe_int(promo.get("route_count", 0)),
        "route_slots": ",".join(promo.get("route_slots", []) or []),
        "role_only": ",".join(promo.get("role_only_enable_required", []) or []),
        "closed_120d": safe_int(m.get("closed_120d", 0)),
        "wins_120d": safe_int(m.get("wins_120d", 0)),
        "losses_120d": safe_int(m.get("losses_120d", 0)),
        "win_rate_120d": safe_float(m.get("win_rate_120d", 0.0)),
        "net_pips_120d": safe_float(m.get("net_pips_120d", 0.0)),
        "max_mae_pips_120d": safe_float(m.get("max_mae_pips_120d", 0.0)),
        "avg_hold_days_120d": safe_float(m.get("avg_hold_days_120d", 9999.0)),
        "closed_30d": safe_int(m.get("closed_30d", 0)),
        "wins_30d": safe_int(m.get("wins_30d", 0)),
        "losses_30d": safe_int(m.get("losses_30d", 0)),
        "sample_quality": promo.get("sample_quality", ""),
        "elapsed_seconds": round(elapsed, 3),
        "result_dir": str(pair_dir),
    }


def error_row(pair: str, pair_dir: Path, elapsed: float, returncode: int, message: str) -> dict:
    return {
        "pair": pair, "tier": TIER_BY_PAIR.get(pair, "custom"), "status": "FAILED",
        "seed_math": "", "guardian": "", "trigger": "", "macro": "", "micro": "",
        "bridge": "", "fourth": "", "route_count": 0, "route_slots": "", "role_only": "",
        "closed_120d": 0, "wins_120d": 0, "losses_120d": 0, "win_rate_120d": 0.0,
        "net_pips_120d": 0.0, "max_mae_pips_120d": 0.0, "avg_hold_days_120d": 9999.0,
        "closed_30d": 0, "wins_30d": 0, "losses_30d": 0, "sample_quality": "",
        "elapsed_seconds": round(elapsed, 3), "result_dir": str(pair_dir),
        "returncode": returncode, "error": message[:1000],
    }


def write_csv(path: Path, rows: List[dict]) -> None:
    if not rows:
        return
    fields = []
    seen = set()
    for row in rows:
        for k in row.keys():
            if k not in seen:
                fields.append(k); seen.add(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows)


def champion_key(row: dict) -> tuple:
    if row.get("status") != "DONE":
        return (0, 0.0, 0, float("-inf"), float("-inf"), float("-inf"), float("-inf"))
    losses = safe_int(row.get("losses_120d", 0))
    closed = safe_int(row.get("closed_120d", 0))
    perfect = 1 if losses == 0 and closed > 0 else 0
    return (
        perfect,
        safe_float(row.get("win_rate_120d", 0.0)),
        closed,
        safe_float(row.get("net_pips_120d", 0.0)),
        -safe_float(row.get("max_mae_pips_120d", 0.0)),
        -safe_float(row.get("avg_hold_days_120d", 9999.0)),
        safe_int(row.get("closed_30d", 0)),
    )


def print_pair_header(index: int, total: int, pair: str) -> None:
    print("\n" + "=" * 84, flush=True)
    print(f"TGIM BATCH {index}/{total} | PAIR BEING SWEPT: {pair} | TIER {TIER_BY_PAIR.get(pair, 'custom')}", flush=True)
    print("=" * 84, flush=True)


def build_command(args: argparse.Namespace, sweeper: Path, pair: str, pair_dir: Path) -> List[str]:
    cmd = [
        sys.executable, str(sweeper),
        "--instrument", pair,
        "--env", args.env,
        "--eval-days", str(args.eval_days),
        "--forward-days", str(args.forward_days),
        "--warmup-days", str(args.warmup_days),
        "--registry-limit", str(args.registry_limit),
        "--seed", args.seed,
        "--expanded-scope", args.expanded_scope,
        "--macro-top-per-seed", str(args.macro_top_per_seed),
        "--bridge-top-per-seed", str(args.bridge_top_per_seed),
        "--cache-dir", args.cache_dir,
        "--result-dir", str(pair_dir),
    ]
    if args.token:
        cmd += ["--token", args.token]
    if args.skip_bridge:
        cmd.append("--skip-bridge")
    if args.skip_fourth:
        cmd.append("--skip-fourth")
    if args.refresh:
        cmd.append("--refresh")
    return cmd


def run_and_tee(cmd: List[str], log_path: Path) -> Tuple[int, str]:
    tail: List[str] = []
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="", flush=True)
            log.write(line); log.flush()
            tail.append(line.rstrip())
            if len(tail) > 40:
                tail = tail[-40:]
        rc = proc.wait()
    return rc, "\n".join(tail)


def write_batch_outputs(root: Path, rows: List[dict], seq: List[str], started_at: str) -> None:
    write_csv(root / "PAIR_STATUS.csv", rows)
    done = sorted((r for r in rows if r.get("status") == "DONE"), key=champion_key, reverse=True)
    write_csv(root / "CHAMPION_LEADERBOARD.csv", done)

    bank: Dict[str, dict] = {}
    for row in rows:
        if row.get("status") != "DONE":
            continue
        promo = Path(str(row["result_dir"])) / "PAIR_PROFILE_PROMOTION.json"
        if promo.exists():
            try:
                bank[row["pair"].replace("_", "")] = read_json(promo)
            except Exception:
                pass
    (root / "PAIR_PROFILE_PROMOTION_BANK.json").write_text(json.dumps(bank, indent=2), encoding="utf-8")

    progress = {
        "batch_build_id": BATCH_BUILD_ID,
        "expected_sweeper_build": EXPECTED_SWEEPER_BUILD,
        "started_at_utc": started_at,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "selected_pairs": seq,
        "selected_count": len(seq),
        "done_count": sum(1 for r in rows if r.get("status") == "DONE"),
        "failed_count": sum(1 for r in rows if r.get("status") == "FAILED"),
        "pending_count": max(0, len(seq) - len(rows)),
        "last_pair": rows[-1]["pair"] if rows else None,
        "last_status": rows[-1]["status"] if rows else None,
    }
    (root / "BATCH_PROGRESS.json").write_text(json.dumps(progress, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    sweeper = Path(args.sweeper).resolve()
    if not sweeper.exists():
        raise SystemExit(f"Sweeper not found: {sweeper}")

    seq = pair_sequence(args)
    if not seq:
        raise SystemExit("No pairs selected")

    # One stable root per invocation unless the user explicitly chooses a named root.
    root = Path(args.result_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc).isoformat()

    print("=" * 84)
    print("TGIM MACRO/MICRO AUTOMATIC PAIR BATCH")
    print(f"BATCH BUILD: {BATCH_BUILD_ID}")
    print(f"SINGLE-PAIR ENGINE: {sweeper.name}")
    print(f"PAIRS SELECTED: {len(seq)}")
    print("SEQUENCE: " + " -> ".join(seq))
    print(f"RESULT ROOT: {root}")
    print("=" * 84, flush=True)

    if args.dry_run:
        for i, pair in enumerate(seq, 1):
            pair_dir = root / pair
            print_pair_header(i, len(seq), pair)
            print(" ".join(build_command(args, sweeper, pair, pair_dir)))
        return 0

    rows: List[dict] = []

    # Resume from existing status CSV if available, but only trust pair result JSONs.
    for i, pair in enumerate(seq, 1):
        print_pair_header(i, len(seq), pair)
        pair_dir = root / pair
        pair_dir.mkdir(parents=True, exist_ok=True)
        promo_path = pair_dir / "PAIR_PROFILE_PROMOTION.json"

        if args.resume and promo_path.exists():
            try:
                promo = read_json(promo_path)
                row = promotion_row(pair, promo, pair_dir, 0.0)
                row["status"] = "SKIPPED_EXISTING"
                rows.append(row)
                print(f"[{pair}] Existing promotion found; skipping (--resume).", flush=True)
                write_batch_outputs(root, rows, seq, started_at)
                continue
            except Exception as exc:
                print(f"[{pair}] Existing promotion unreadable; rerunning: {exc}", flush=True)

        cmd = build_command(args, sweeper, pair, pair_dir)
        print(f"[{pair}] COMMAND: {' '.join(cmd)}", flush=True)
        t0 = time.monotonic()
        rc, tail = run_and_tee(cmd, pair_dir / "SWEEPER_STDOUT.log")
        elapsed = time.monotonic() - t0

        if rc == 0 and promo_path.exists():
            try:
                promo = read_json(promo_path)
                row = promotion_row(pair, promo, pair_dir, elapsed)
                rows.append(row)
                print(
                    f"[{pair}] COMPLETE | G {row['guardian']} | T {row['trigger']} | "
                    f"Macro {row['macro']} | Micro {row['micro']} | routes {row['route_slots']} | "
                    f"{row['wins_120d']}/{row['closed_120d']} | {row['win_rate_120d']:.2f}%",
                    flush=True,
                )
            except Exception as exc:
                row = error_row(pair, pair_dir, elapsed, rc, f"Promotion parse failed: {exc}\n{tail}")
                rows.append(row)
                print(f"[{pair}] FAILED TO PARSE PROMOTION: {exc}", flush=True)
        else:
            row = error_row(pair, pair_dir, elapsed, rc, tail or "No promotion file produced")
            rows.append(row)
            print(f"[{pair}] FAILED | exit={rc}; continuing={not args.stop_on_error}", flush=True)

        write_batch_outputs(root, rows, seq, started_at)

        if row["status"] == "FAILED" and args.stop_on_error:
            break

    # Reclassify resume rows as DONE in final outputs so leaderboard includes them.
    for row in rows:
        if row.get("status") == "SKIPPED_EXISTING":
            row["status"] = "DONE"
    write_batch_outputs(root, rows, seq, started_at)

    done = [r for r in rows if r.get("status") == "DONE"]
    failed = [r for r in rows if r.get("status") == "FAILED"]
    leaderboard = sorted(done, key=champion_key, reverse=True)

    print("\n" + "=" * 84)
    print("TGIM AUTOMATIC BATCH COMPLETE")
    print(f"DONE: {len(done)} | FAILED: {len(failed)} | SELECTED: {len(seq)}")
    if leaderboard:
        top = leaderboard[0]
        print(
            f"CURRENT BATCH LEADER: {top['pair']} | {top['wins_120d']}/{top['closed_120d']} | "
            f"{top['win_rate_120d']:.2f}% | G {top['guardian']} | T {top['trigger']} | "
            f"Macro {top['macro']} | Micro {top['micro']} | routes {top['route_slots']}"
        )
    print(f"PAIR STATUS: {root / 'PAIR_STATUS.csv'}")
    print(f"LEADERBOARD: {root / 'CHAMPION_LEADERBOARD.csv'}")
    print(f"PROMOTION BANK: {root / 'PAIR_PROFILE_PROMOTION_BANK.json'}")
    print("=" * 84, flush=True)

    # Continue-through-errors is the default; nonzero only if nothing completed.
    return 0 if done else 2


if __name__ == "__main__":
    raise SystemExit(main())
