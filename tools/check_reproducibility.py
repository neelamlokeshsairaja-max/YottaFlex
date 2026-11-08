"""Run the same pipeline twice and compare immutable artifact hashes."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from src.pipeline import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scale", choices=("starter", "full"), default="starter")
    parser.add_argument("--seed", type=int, default=20261022)
    args = parser.parse_args()
    output = ROOT / "data" / "reproducibility_runs"
    first, _ = run_pipeline(args.scale == "full", args.seed, output)
    first_manifest = json.loads((first / "source_manifest.json").read_text(encoding="utf-8"))
    second, _ = run_pipeline(args.scale == "full", args.seed, output)
    second_manifest = json.loads((second / "source_manifest.json").read_text(encoding="utf-8"))
    equal = first_manifest["artifacts"] == second_manifest["artifacts"]
    report = {
        "scale": args.scale,
        "seed": args.seed,
        "run_id": first_manifest["run_id"],
        "artifact_hashes_equal": equal,
        "artifact_count": len(first_manifest["artifacts"]),
        "row_counts": first_manifest["row_counts"],
    }
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "reproducibility_report.md").write_text(
        "# Reproducibility report\n\n"
        f"```json\n{json.dumps(report, indent=2, sort_keys=True)}\n```\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if not equal:
        raise SystemExit("Reproducibility check failed: artifact hashes differ")


if __name__ == "__main__":
    main()
