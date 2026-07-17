#!/usr/bin/env python3
"""
Build core preparation artifacts for a Stage1 program from normalized catalog index.

This script does not modify binaries. It prepares family readiness, operation profiles,
and backlog datasets for systematic catalog-wide implementation.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence


def split_pipe(value: str) -> List[str]:
    if not value:
        return []
    return [v for v in value.split("|") if v]


@dataclass
class IndexRecord:
    rel_path: str
    file_name: str
    extension: str
    size_bytes: int
    sha256: str
    ecu_candidates: List[str]
    brand_candidates: List[str]
    software_candidates: List[str]
    features: List[str]
    inferred_role: str


@dataclass
class FamilyAggregate:
    family_key: str
    software_id: str
    ecu_primary: str
    brands: List[str]
    files_total: int
    unique_hashes: int
    size_min: int
    size_max: int
    role_counts: Dict[str, int]
    feature_counts: Dict[str, int]
    has_stage1: bool
    has_euro2: bool
    readiness_score: int
    readiness_status: str
    next_action: str

    def to_row(self) -> Dict[str, str]:
        roles = ",".join(f"{k}:{v}" for k, v in sorted(self.role_counts.items()))
        features = ",".join(f"{k}:{v}" for k, v in sorted(self.feature_counts.items()))
        return {
            "family_key": self.family_key,
            "software_id": self.software_id,
            "ecu_primary": self.ecu_primary,
            "brands": "|".join(self.brands),
            "files_total": str(self.files_total),
            "unique_hashes": str(self.unique_hashes),
            "size_min_bytes": str(self.size_min),
            "size_max_bytes": str(self.size_max),
            "role_counts": roles,
            "feature_counts": features,
            "has_stage1": "true" if self.has_stage1 else "false",
            "has_euro2": "true" if self.has_euro2 else "false",
            "readiness_score": str(self.readiness_score),
            "readiness_status": self.readiness_status,
            "next_action": self.next_action,
        }

    def stage1_ready(self) -> bool:
        return self.readiness_status == "ready_for_template"

    def euro2_ready(self) -> bool:
        return self.readiness_status == "ready_for_template"

    def default_operation(self) -> str:
        if self.has_euro2:
            return "euro2"
        if self.has_stage1:
            return "stage1"
        return "euro2"


def choose_family_key(record: IndexRecord) -> str:
    if record.software_candidates:
        return f"SW:{record.software_candidates[0]}"
    if record.ecu_candidates:
        return f"ECU:{record.ecu_candidates[0]}:SIZE:{record.size_bytes}"
    return f"HASH:{record.sha256[:12]}"


def calc_readiness(
    has_stock_like: bool,
    has_modified: bool,
    unique_hashes: int,
    has_ecu: bool,
    has_sw: bool,
    has_stage1_or_euro2: bool,
) -> int:
    score = 0
    if has_stock_like:
        score += 35
    if has_modified:
        score += 25
    if unique_hashes >= 2:
        score += 15
    if has_ecu:
        score += 15
    if has_sw:
        score += 10
    if has_stage1_or_euro2:
        score += 10
    return min(score, 100)


def readiness_status(score: int) -> str:
    if score >= 75:
        return "ready_for_template"
    if score >= 40:
        return "partial"
    return "needs_data"


def readiness_action(status: str) -> str:
    if status == "ready_for_template":
        return "prepare_map-template-and-validation-checklist"
    if status == "partial":
        return "collect-missing-stock-or-mod-reference"
    return "enrich-family-metadata-and-samples"


def read_index(path: Path) -> List[IndexRecord]:
    items: List[IndexRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            items.append(
                IndexRecord(
                    rel_path=row["rel_path"],
                    file_name=row["file_name"],
                    extension=row["extension"],
                    size_bytes=int(row["size_bytes"]),
                    sha256=row["sha256"],
                    ecu_candidates=split_pipe(row["ecu_candidates"]),
                    brand_candidates=split_pipe(row["brand_candidates"]),
                    software_candidates=split_pipe(row["software_candidates"]),
                    features=split_pipe(row["features"]),
                    inferred_role=row["inferred_role"],
                )
            )
    return items


def build_families(records: Sequence[IndexRecord]) -> List[FamilyAggregate]:
    groups: Dict[str, List[IndexRecord]] = {}
    for record in records:
        key = choose_family_key(record)
        groups.setdefault(key, []).append(record)

    output: List[FamilyAggregate] = []
    for key, group in sorted(groups.items()):
        brands = sorted({brand for r in group for brand in r.brand_candidates})
        ecus = sorted({ecu for r in group for ecu in r.ecu_candidates})
        sw_ids = sorted({sw for r in group for sw in r.software_candidates})
        hashes = {r.sha256 for r in group}
        role_counts: Dict[str, int] = {}
        feature_counts: Dict[str, int] = {}
        for record in group:
            role_counts[record.inferred_role] = role_counts.get(record.inferred_role, 0) + 1
            for feature in record.features:
                feature_counts[feature] = feature_counts.get(feature, 0) + 1

        has_stock_like = bool(role_counts.get("stock") or role_counts.get("stock_inferred"))
        has_modified = bool(role_counts.get("modified"))
        has_stage1 = "stage1" in feature_counts
        has_euro2 = "euro2" in feature_counts
        score = calc_readiness(
            has_stock_like=has_stock_like,
            has_modified=has_modified,
            unique_hashes=len(hashes),
            has_ecu=bool(ecus),
            has_sw=bool(sw_ids),
            has_stage1_or_euro2=(has_stage1 or has_euro2),
        )
        status = readiness_status(score)
        output.append(
            FamilyAggregate(
                family_key=key,
                software_id=sw_ids[0] if sw_ids else "",
                ecu_primary=ecus[0] if ecus else "",
                brands=brands,
                files_total=len(group),
                unique_hashes=len(hashes),
                size_min=min(r.size_bytes for r in group),
                size_max=max(r.size_bytes for r in group),
                role_counts=role_counts,
                feature_counts=feature_counts,
                has_stage1=has_stage1,
                has_euro2=has_euro2,
                readiness_score=score,
                readiness_status=status,
                next_action=readiness_action(status),
            )
        )
    return output


def write_csv(path: Path, rows: Sequence[Dict[str, str]], fields: Sequence[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_profiles(path: Path) -> None:
    profiles = {
        "version": "v1",
        "principles": [
            "Systemic catalog rules only; no brand-specific dialog hacks.",
            "Normalize operation aliases before any routing.",
            "Separate preparation/validation from binary transformation modules.",
        ],
        "operations": {
            "stage1": {
                "aliases": ["stage1", "stage 1", "st1", "rt47 stage1", "modrt47 stage1"],
                "required_inputs": ["stock_reference", "target_file", "family_id_or_software_id"],
                "validation_checks": [
                    "ecu-family-consistency",
                    "size-compatibility",
                    "checksum-pipeline-available",
                    "post-build-diff-within-expected-zones",
                ],
            },
            "euro2": {
                "aliases": ["euro2", "euro-2", "e2", "mod e2", "евро2"],
                "required_inputs": ["stock_reference", "target_file", "family_id_or_software_id"],
                "validation_checks": [
                    "ecu-family-consistency",
                    "size-compatibility",
                    "dtc-table-presence-check",
                    "post-build-diff-within-expected-zones",
                ],
            },
        },
    }
    path.write_text(json.dumps(profiles, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_summary(path: Path, families: Sequence[FamilyAggregate]) -> None:
    status_counts: Dict[str, int] = {}
    for family in families:
        status_counts[family.readiness_status] = status_counts.get(family.readiness_status, 0) + 1
    lines = [
        "Stage core builder summary",
        f"families_total={len(families)}",
        "readiness_status_counts:",
    ]
    for status, count in sorted(status_counts.items()):
        lines.append(f"  {status}: {count}")
    top_ready = sorted(families, key=lambda f: f.readiness_score, reverse=True)[:10]
    lines.append("top_families_by_readiness:")
    for family in top_ready:
        lines.append(
            f"  {family.family_key} | score={family.readiness_score} | status={family.readiness_status} | files={family.files_total}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_operation_matrix(families: Sequence[FamilyAggregate]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for family in families:
        rows.append(
            {
                "family_key": family.family_key,
                "software_id": family.software_id,
                "ecu_primary": family.ecu_primary,
                "readiness_status": family.readiness_status,
                "readiness_score": str(family.readiness_score),
                "has_stage1_signal": "true" if family.has_stage1 else "false",
                "has_euro2_signal": "true" if family.has_euro2 else "false",
                "stage1_ready": "true" if family.stage1_ready() else "false",
                "euro2_ready": "true" if family.euro2_ready() else "false",
                "target_operations": "stage1|euro2",
                "default_operation": family.default_operation(),
                "recommended_action": family.next_action,
            }
        )
    return rows


def build_brand_roadmap(
    families: Sequence[FamilyAggregate],
    ident_priority_csv: Path,
) -> List[Dict[str, str]]:
    if not ident_priority_csv.exists():
        return []

    fam_by_sw: Dict[str, FamilyAggregate] = {}
    fam_by_ecu: Dict[str, FamilyAggregate] = {}
    for family in families:
        if family.software_id:
            fam_by_sw[family.software_id.upper()] = family
        if family.ecu_primary:
            fam_by_ecu[family.ecu_primary.upper()] = family

    rows: List[Dict[str, str]] = []
    with ident_priority_csv.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            target_brand = row.get("target_brand", "")
            software_id = row.get("software_id", "").upper()
            ecu_primary = row.get("ecu_primary", "").upper()
            family = None
            match_type = ""
            if software_id and software_id in fam_by_sw:
                family = fam_by_sw[software_id]
                match_type = "software_id"
            elif ecu_primary and ecu_primary in fam_by_ecu:
                family = fam_by_ecu[ecu_primary]
                match_type = "ecu_primary"

            rows.append(
                {
                    "target_brand": target_brand,
                    "priority_source": row.get("priority_source", ""),
                    "family_key": row.get("family_key", ""),
                    "software_id": row.get("software_id", ""),
                    "ecu_primary": row.get("ecu_primary", ""),
                    "matched_stage_family": family.family_key if family else "",
                    "match_type": match_type,
                    "readiness_status": family.readiness_status if family else "needs_data",
                    "readiness_score": str(family.readiness_score) if family else "0",
                    "target_operations": "stage1|euro2",
                    "default_operation": family.default_operation() if family else "euro2",
                    "stage1_ready": "true" if family and family.stage1_ready() else "false",
                    "euro2_ready": "true" if family and family.euro2_ready() else "false",
                    "recommended_action": (
                        family.next_action if family else "collect-stock-mod-pair-and-ident-docs"
                    ),
                }
            )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Stage1 core prep artifacts from index csv.")
    parser.add_argument("--index-csv", required=True, help="Path to firmware_catalog_index.csv")
    parser.add_argument("--out-dir", required=True, help="Output directory")
    parser.add_argument(
        "--ident-priority-csv",
        default="",
        help="Optional ident_brand_priority_toyota_haval.csv for roadmap merge.",
    )
    args = parser.parse_args()

    index_csv = Path(args.index_csv).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    records = read_index(index_csv)
    families = build_families(records)

    families_csv = out_dir / "stage_core_families.csv"
    backlog_csv = out_dir / "stage_core_backlog.csv"
    profiles_json = out_dir / "stage_core_operation_profiles.json"
    matrix_csv = out_dir / "stage_core_operation_matrix.csv"
    euro2_queue_csv = out_dir / "stage_core_euro2_queue.csv"
    summary_txt = out_dir / "stage_core_summary.txt"
    roadmap_csv = out_dir / "stage_core_brand_roadmap.csv"

    write_csv(
        families_csv,
        [item.to_row() for item in families],
        [
            "family_key",
            "software_id",
            "ecu_primary",
            "brands",
            "files_total",
            "unique_hashes",
            "size_min_bytes",
            "size_max_bytes",
            "role_counts",
            "feature_counts",
            "has_stage1",
            "has_euro2",
            "readiness_score",
            "readiness_status",
            "next_action",
        ],
    )

    backlog_rows = [
        family.to_row() for family in families if family.readiness_status in {"partial", "needs_data"}
    ]
    write_csv(
        backlog_csv,
        backlog_rows,
        [
            "family_key",
            "software_id",
            "ecu_primary",
            "brands",
            "files_total",
            "unique_hashes",
            "size_min_bytes",
            "size_max_bytes",
            "role_counts",
            "feature_counts",
            "has_stage1",
            "has_euro2",
            "readiness_score",
            "readiness_status",
            "next_action",
        ],
    )
    write_profiles(profiles_json)
    operation_matrix = build_operation_matrix(families)
    write_csv(
        matrix_csv,
        operation_matrix,
        [
            "family_key",
            "software_id",
            "ecu_primary",
            "readiness_status",
            "readiness_score",
            "has_stage1_signal",
            "has_euro2_signal",
            "stage1_ready",
            "euro2_ready",
            "target_operations",
            "default_operation",
            "recommended_action",
        ],
    )
    write_csv(
        euro2_queue_csv,
        [row for row in operation_matrix if row["euro2_ready"] == "true"],
        [
            "family_key",
            "software_id",
            "ecu_primary",
            "readiness_status",
            "readiness_score",
            "has_stage1_signal",
            "has_euro2_signal",
            "stage1_ready",
            "euro2_ready",
            "target_operations",
            "default_operation",
            "recommended_action",
        ],
    )
    write_summary(summary_txt, families)

    roadmap_rows: List[Dict[str, str]] = []
    if args.ident_priority_csv:
        ident_path = Path(args.ident_priority_csv).expanduser().resolve()
        roadmap_rows = build_brand_roadmap(families, ident_priority_csv=ident_path)
        write_csv(
            roadmap_csv,
            roadmap_rows,
            [
                "target_brand",
                "priority_source",
                "family_key",
                "software_id",
                "ecu_primary",
                "matched_stage_family",
                "match_type",
                "readiness_status",
                "readiness_score",
                "target_operations",
                "default_operation",
                "stage1_ready",
                "euro2_ready",
                "recommended_action",
            ],
        )

    print(f"records={len(records)}")
    print(f"families={len(families)}")
    if args.ident_priority_csv:
        print(f"roadmap_rows={len(roadmap_rows)}")
    print(f"written={families_csv}")
    print(f"written={backlog_csv}")
    print(f"written={profiles_json}")
    print(f"written={matrix_csv}")
    print(f"written={euro2_queue_csv}")
    print(f"written={summary_txt}")
    if args.ident_priority_csv:
        print(f"written={roadmap_csv}")


if __name__ == "__main__":
    main()
