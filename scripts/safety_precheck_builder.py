#!/usr/bin/env python3
"""
Generate safety precheck task lists from family manifest.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List, Sequence


def split_pipe(value: str) -> List[str]:
    if not value:
        return []
    return [item for item in value.split("|") if item]


def write_csv(path: Path, rows: Sequence[Dict[str, str]], fields: Sequence[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build safety precheck queues from family manifest.")
    parser.add_argument("--manifest-csv", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    manifest_csv = Path(args.manifest_csv).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: List[Dict[str, str]] = []
    with manifest_csv.open("r", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    precheck_tasks_raw: List[Dict[str, str]] = []
    controlled_queue: List[Dict[str, str]] = []
    task_index = 1
    for row in rows:
        brand = row.get("target_brand", "")
        family_key = row.get("family_key", "")
        software_id = row.get("software_id", "")
        ecu = row.get("ecu_primary", "")
        blockers = split_pipe(row.get("blockers", ""))
        gate = row.get("safety_gate_status", "")
        risk = row.get("risk_level", "")
        default_operation = row.get("default_operation", "euro2")

        if gate == "READY_FOR_CONTROLLED_BUILD":
            controlled_queue.append(
                {
                    "target_brand": brand,
                    "family_key": family_key,
                    "software_id": software_id,
                    "ecu_primary": ecu,
                    "default_operation": default_operation,
                    "readiness_status": row.get("readiness_status", ""),
                    "readiness_score": row.get("readiness_score", ""),
                    "required_final_checks": "checksum_verified_project|diff_scope_verified|backup_present",
                    "queue_status": "ready",
                }
            )
            continue

        # Missing references
        if any(item.startswith("missing_stock_reference") for item in blockers):
            precheck_tasks_raw.append(
                {
                    "task_id": f"T{task_index:04d}",
                    "target_brand": brand,
                    "family_key": family_key,
                    "software_id": software_id,
                    "ecu_primary": ecu,
                    "risk_level": risk,
                    "task_type": "collect_stock_reference",
                    "check_item": "Provide stock binary for this family",
                    "evidence_required": "stock_file + sha256 + source note",
                    "status": "pending",
                }
            )
            task_index += 1
        if any(item.startswith("missing_modified_reference") for item in blockers):
            precheck_tasks_raw.append(
                {
                    "task_id": f"T{task_index:04d}",
                    "target_brand": brand,
                    "family_key": family_key,
                    "software_id": software_id,
                    "ecu_primary": ecu,
                    "risk_level": risk,
                    "task_type": "collect_modified_reference",
                    "check_item": "Provide modified binary reference",
                    "evidence_required": "mod_file + sha256 + operation tag",
                    "status": "pending",
                }
            )
            task_index += 1
        checksum_blockers = [item for item in blockers if item.startswith("checksum_not_verified")]
        if checksum_blockers:
            precheck_tasks_raw.append(
                {
                    "task_id": f"T{task_index:04d}",
                    "target_brand": brand,
                    "family_key": family_key,
                    "software_id": software_id,
                    "ecu_primary": ecu,
                    "risk_level": risk,
                    "task_type": "verify_checksum_path",
                    "check_item": "Project-level checksum verification required",
                    "evidence_required": "verified checksum module/toolchain + test proof",
                    "status": "pending",
                }
            )
            task_index += 1

    # Deduplicate by brand + software + task type.
    dedup_index: Dict[tuple, Dict[str, str]] = {}
    for row in precheck_tasks_raw:
        key = (
            row.get("target_brand", ""),
            row.get("software_id", ""),
            row.get("task_type", ""),
            row.get("risk_level", ""),
        )
        if key not in dedup_index:
            dedup_index[key] = dict(row)
            dedup_index[key]["family_keys"] = row.get("family_key", "")
            continue
        existing = dedup_index[key]
        current = set(split_pipe(existing.get("family_keys", "")))
        current.add(row.get("family_key", ""))
        existing["family_keys"] = "|".join(sorted(item for item in current if item))

    precheck_tasks = list(dedup_index.values())
    for i, row in enumerate(precheck_tasks, 1):
        row["task_id"] = f"T{i:04d}"

    precheck_csv = out_dir / "safety_precheck_tasks.csv"
    queue_csv = out_dir / "controlled_build_queue.csv"
    summary_txt = out_dir / "safety_precheck_summary.txt"

    write_csv(
        precheck_csv,
        precheck_tasks,
        [
            "task_id",
            "target_brand",
            "family_key",
            "family_keys",
            "software_id",
            "ecu_primary",
            "risk_level",
            "task_type",
            "check_item",
            "evidence_required",
            "status",
        ],
    )
    write_csv(
        queue_csv,
        controlled_queue,
        [
            "target_brand",
            "family_key",
            "software_id",
            "ecu_primary",
            "default_operation",
            "readiness_status",
            "readiness_score",
            "required_final_checks",
            "queue_status",
        ],
    )

    summary_lines = [
        "Safety precheck summary",
        f"manifest_rows={len(rows)}",
        f"precheck_tasks_raw={len(precheck_tasks_raw)}",
        f"precheck_tasks_deduplicated={len(precheck_tasks)}",
        f"controlled_build_queue={len(controlled_queue)}",
    ]
    summary_txt.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    print(f"manifest_rows={len(rows)}")
    print(f"precheck_tasks={len(precheck_tasks)}")
    print(f"controlled_build_queue={len(controlled_queue)}")
    print(f"written={precheck_csv}")
    print(f"written={queue_csv}")
    print(f"written={summary_txt}")


if __name__ == "__main__":
    main()
