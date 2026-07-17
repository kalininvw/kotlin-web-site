#!/usr/bin/env python3
"""
Build a unified family manifest for controlled Stage1/Euro2 pipeline execution.

Design goal: conservative safety gates.
No family is considered safe for controlled build unless prerequisites are explicit.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple


def split_pipe(value: str) -> List[str]:
    if not value:
        return []
    return [item for item in value.split("|") if item]


def truthy(value: str) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


@dataclass
class FirmwareIndexRecord:
    rel_path: str
    sha256: str
    size_bytes: int
    ecu_candidates: List[str]
    brand_candidates: List[str]
    software_candidates: List[str]
    features: List[str]
    inferred_role: str


@dataclass
class StageFamily:
    family_key: str
    software_id: str
    ecu_primary: str
    readiness_score: int
    readiness_status: str
    has_stage1_signal: bool
    has_euro2_signal: bool
    stage1_ready: bool
    euro2_ready: bool
    default_operation: str
    recommended_action: str


@dataclass
class IdentPriority:
    target_brand: str
    priority_source: str
    family_key: str
    family_type: str
    software_id: str
    ecu_primary: str
    ecu_candidates: List[str]
    brand_candidates: List[str]
    doc_count: int


def read_firmware_index(path: Path) -> List[FirmwareIndexRecord]:
    items: List[FirmwareIndexRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            items.append(
                FirmwareIndexRecord(
                    rel_path=row.get("rel_path", ""),
                    sha256=row.get("sha256", ""),
                    size_bytes=int(row.get("size_bytes", "0")),
                    ecu_candidates=split_pipe(row.get("ecu_candidates", "")),
                    brand_candidates=split_pipe(row.get("brand_candidates", "")),
                    software_candidates=split_pipe(row.get("software_candidates", "")),
                    features=split_pipe(row.get("features", "")),
                    inferred_role=row.get("inferred_role", ""),
                )
            )
    return items


def read_stage_families(path: Path) -> Dict[str, StageFamily]:
    if not path.exists():
        return {}
    by_sw: Dict[str, StageFamily] = {}
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            sw = row.get("software_id", "").upper()
            if not sw:
                continue
            by_sw[sw] = StageFamily(
                family_key=row.get("family_key", ""),
                software_id=sw,
                ecu_primary=row.get("ecu_primary", ""),
                readiness_score=int(row.get("readiness_score", "0")),
                readiness_status=row.get("readiness_status", ""),
                has_stage1_signal=truthy(row.get("has_stage1", "false")),
                has_euro2_signal=truthy(row.get("has_euro2", "false")),
                stage1_ready=truthy(row.get("has_stage1", "false")) or row.get("readiness_status", "") == "ready_for_template",
                euro2_ready=truthy(row.get("has_euro2", "false")) or row.get("readiness_status", "") == "ready_for_template",
                default_operation="euro2" if truthy(row.get("has_euro2", "false")) else ("stage1" if truthy(row.get("has_stage1", "false")) else "euro2"),
                recommended_action=row.get("next_action", ""),
            )
    return by_sw


def read_ident_priority(path: Path) -> List[IdentPriority]:
    if not path.exists():
        return []
    rows: List[IdentPriority] = []
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(
                IdentPriority(
                    target_brand=row.get("target_brand", ""),
                    priority_source=row.get("priority_source", ""),
                    family_key=row.get("family_key", ""),
                    family_type=row.get("family_type", ""),
                    software_id=row.get("software_id", "").upper(),
                    ecu_primary=row.get("ecu_primary", ""),
                    ecu_candidates=split_pipe(row.get("ecu_candidates", "")),
                    brand_candidates=split_pipe(row.get("brand_candidates", "")),
                    doc_count=int(row.get("doc_count", "0") or "0"),
                )
            )
    return rows


def read_checksum_registry(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def infer_checksum_status(
    software_id: str,
    ecu_primary: str,
    registry: Dict[str, object],
) -> Tuple[str, str]:
    """
    Returns (status, source).
    status values:
      - verified_project
      - conditional_support
      - unknown
    """
    by_ecu = registry.get("by_ecu", {}) if isinstance(registry, dict) else {}
    by_sw_prefix = registry.get("by_sw_prefix", {}) if isinstance(registry, dict) else {}

    ecu_upper = ecu_primary.upper()
    if isinstance(by_ecu, dict) and ecu_upper in by_ecu:
        data = by_ecu[ecu_upper]
        if isinstance(data, dict):
            return str(data.get("status", "unknown")), f"ecu:{ecu_upper}"

    sw_upper = software_id.upper()
    if isinstance(by_sw_prefix, dict):
        for prefix, data in by_sw_prefix.items():
            if sw_upper.startswith(prefix.upper()):
                if isinstance(data, dict):
                    return str(data.get("status", "unknown")), f"sw_prefix:{prefix}"

    return "unknown", "none"


def build_firmware_aggregates(
    records: Sequence[FirmwareIndexRecord],
) -> Tuple[Dict[str, Dict[str, object]], Dict[str, Counter[str]], Dict[str, Counter[str]]]:
    by_sw: Dict[str, Dict[str, object]] = {}
    sw_by_ecu_counter: Dict[str, Counter[str]] = defaultdict(Counter)
    sw_by_brand_counter: Dict[str, Counter[str]] = defaultdict(Counter)

    for record in records:
        sw_ids = [sw.upper() for sw in record.software_candidates if sw]
        for sw in sw_ids:
            slot = by_sw.setdefault(
                sw,
                {
                    "files": set(),
                    "stock_files": set(),
                    "mod_files": set(),
                    "sizes": set(),
                    "ecus": set(),
                    "brands": set(),
                    "stock_sha": set(),
                    "mod_sha": set(),
                    "features": set(),
                    "roles": Counter(),
                },
            )
            slot["files"].add(record.rel_path)  # type: ignore[index]
            slot["sizes"].add(record.size_bytes)  # type: ignore[index]
            slot["ecus"].update(record.ecu_candidates)  # type: ignore[index]
            slot["brands"].update(record.brand_candidates)  # type: ignore[index]
            slot["features"].update(record.features)  # type: ignore[index]
            slot["roles"][record.inferred_role] += 1  # type: ignore[index]
            if record.inferred_role in {"stock", "stock_inferred"}:
                slot["stock_files"].add(record.rel_path)  # type: ignore[index]
                slot["stock_sha"].add(record.sha256)  # type: ignore[index]
            if record.inferred_role == "modified":
                slot["mod_files"].add(record.rel_path)  # type: ignore[index]
                slot["mod_sha"].add(record.sha256)  # type: ignore[index]

            for ecu in record.ecu_candidates:
                sw_by_ecu_counter[ecu.upper()][sw] += 1
            for brand in record.brand_candidates:
                sw_by_brand_counter[brand.upper()][sw] += 1

    return by_sw, sw_by_ecu_counter, sw_by_brand_counter


def choose_sw_for_ident(
    ident: IdentPriority,
    sw_by_ecu_counter: Dict[str, Counter[str]],
    sw_by_brand_counter: Dict[str, Counter[str]],
) -> str:
    if ident.software_id:
        return ident.software_id
    if ident.ecu_primary:
        counter = sw_by_ecu_counter.get(ident.ecu_primary.upper())
        if counter:
            return counter.most_common(1)[0][0]
    for ecu in ident.ecu_candidates:
        counter = sw_by_ecu_counter.get(ecu.upper())
        if counter:
            return counter.most_common(1)[0][0]
    for brand in ident.brand_candidates:
        counter = sw_by_brand_counter.get(brand.upper())
        if counter:
            return counter.most_common(1)[0][0]
    return ""


def canonical_brand(target_brand: str, brands: Iterable[str]) -> str:
    if target_brand:
        return target_brand.upper()
    upper = {brand.upper() for brand in brands}
    if "TOYOTA" in upper or "LEXUS" in upper:
        return "TOYOTA"
    if "HAVAL" in upper or "GREAT WALL" in upper or "WEY" in upper or "TANK" in upper:
        return "HAVAL"
    if upper:
        return sorted(upper)[0]
    return "UNKNOWN"


def build_manifest(
    ident_rows: Sequence[IdentPriority],
    stage_by_sw: Dict[str, StageFamily],
    by_sw: Dict[str, Dict[str, object]],
    sw_by_ecu_counter: Dict[str, Counter[str]],
    sw_by_brand_counter: Dict[str, Counter[str]],
    checksum_registry: Dict[str, object],
) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for ident in ident_rows:
        chosen_sw = choose_sw_for_ident(ident, sw_by_ecu_counter, sw_by_brand_counter).upper()
        fw = by_sw.get(chosen_sw, {})
        stage = stage_by_sw.get(chosen_sw)

        ecus: Set[str] = set(ident.ecu_candidates)
        brands: Set[str] = set(ident.brand_candidates)
        if fw:
            ecus.update(fw.get("ecus", set()))  # type: ignore[arg-type]
            brands.update(fw.get("brands", set()))  # type: ignore[arg-type]
        if ident.ecu_primary:
            ecus.add(ident.ecu_primary)

        ecu_primary = ident.ecu_primary or (sorted(ecus)[0] if ecus else (stage.ecu_primary if stage else ""))
        brand = canonical_brand(ident.target_brand, brands)

        stock_files = sorted(fw.get("stock_files", set())) if fw else []
        mod_files = sorted(fw.get("mod_files", set())) if fw else []
        stock_sha = sorted(fw.get("stock_sha", set())) if fw else []
        mod_sha = sorted(fw.get("mod_sha", set())) if fw else []
        sizes = sorted(fw.get("sizes", set())) if fw else []
        roles = fw.get("roles", Counter()) if fw else Counter()

        checksum_status, checksum_source = infer_checksum_status(
            software_id=chosen_sw,
            ecu_primary=ecu_primary,
            registry=checksum_registry,
        )

        blockers: List[str] = []
        if not stock_files:
            blockers.append("missing_stock_reference")
        if not mod_files:
            blockers.append("missing_modified_reference")
        if checksum_status != "verified_project":
            blockers.append(f"checksum_not_verified:{checksum_status}")

        if blockers:
            if "missing_stock_reference" in blockers or "missing_modified_reference" in blockers:
                gate_status = "BLOCKED"
                risk_level = "high"
            else:
                gate_status = "PRECHECK_REQUIRED"
                risk_level = "medium"
        else:
            gate_status = "READY_FOR_CONTROLLED_BUILD"
            risk_level = "low"

        stage1_ready = "false"
        euro2_ready = "false"
        readiness_score = "0"
        readiness_status = "needs_data"
        default_operation = "euro2"
        recommended_action = "collect-more-data"
        if stage:
            stage1_ready = "true" if stage.stage1_ready else "false"
            euro2_ready = "true" if stage.euro2_ready else "false"
            readiness_score = str(stage.readiness_score)
            readiness_status = stage.readiness_status
            default_operation = stage.default_operation
            recommended_action = stage.recommended_action
        if gate_status != "READY_FOR_CONTROLLED_BUILD":
            if gate_status == "BLOCKED":
                recommended_action = "collect-missing-stock-mod-binaries"
            elif gate_status == "PRECHECK_REQUIRED":
                recommended_action = "verify-checksum-capability-before-build"

        rows.append(
            {
                "target_brand": brand,
                "family_key": ident.family_key,
                "family_type": ident.family_type,
                "software_id": chosen_sw,
                "ecu_primary": ecu_primary,
                "ecu_candidates": "|".join(sorted(ecus)),
                "brand_candidates": "|".join(sorted(brands)),
                "doc_count": str(ident.doc_count),
                "stock_file_count": str(len(stock_files)),
                "mod_file_count": str(len(mod_files)),
                "stock_sha256": "|".join(stock_sha),
                "mod_sha256": "|".join(mod_sha),
                "size_bytes_observed": "|".join(str(value) for value in sizes),
                "role_counts": ",".join(f"{k}:{v}" for k, v in sorted(roles.items())),
                "stage1_ready": stage1_ready,
                "euro2_ready": euro2_ready,
                "default_operation": default_operation,
                "readiness_score": readiness_score,
                "readiness_status": readiness_status,
                "checksum_status": checksum_status,
                "checksum_source": checksum_source,
                "safety_gate_status": gate_status,
                "risk_level": risk_level,
                "blockers": "|".join(blockers),
                "recommended_action": recommended_action,
            }
        )
    return rows


def write_csv(path: Path, rows: Sequence[Dict[str, str]], fields: Sequence[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(path: Path, rows: Sequence[Dict[str, str]]) -> None:
    gate_counts: Counter[str] = Counter(row.get("safety_gate_status", "") for row in rows)
    brand_counts: Counter[str] = Counter(row.get("target_brand", "") for row in rows)
    lines = [
        "Family manifest summary",
        f"rows_total={len(rows)}",
        "gate_counts:",
    ]
    for key, value in sorted(gate_counts.items()):
        lines.append(f"  {key}: {value}")
    lines.append("brand_counts:")
    for key, value in sorted(brand_counts.items()):
        lines.append(f"  {key}: {value}")
    lines.append("high_risk_families:")
    for row in rows:
        if row.get("risk_level") == "high":
            lines.append(
                f"  {row.get('target_brand')} | {row.get('family_key')} | blockers={row.get('blockers')}"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def default_checksum_registry() -> Dict[str, object]:
    return {
        "version": "v1",
        "notes": [
            "Conservative defaults: known ECU family support does not imply project-level verified checksum.",
            "Set status=verified_project only when checksum path was explicitly validated for that project.",
        ],
        "by_ecu": {
            "MG1UA008": {
                "status": "conditional_support",
                "comment": "Public tooling indicates support, but project-level verification is still required.",
            },
            "MG1US008": {
                "status": "conditional_support",
                "comment": "Public tooling indicates support, but project-level verification is still required.",
            },
            "MG1US708": {
                "status": "conditional_support",
                "comment": "Public tooling indicates support, but project-level verification is still required.",
            },
        },
        "by_sw_prefix": {
            "89663-": {
                "status": "unknown",
                "comment": "Software prefix alone is insufficient for checksum readiness.",
            },
            "F01R": {
                "status": "conditional_support",
                "comment": "Requires ECU-level and toolchain verification per project.",
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build unified family manifest with safety gates.")
    parser.add_argument("--firmware-index-csv", required=True)
    parser.add_argument("--ident-priority-csv", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--stage-families-csv", default="")
    parser.add_argument("--checksum-registry-json", default="")
    args = parser.parse_args()

    firmware_index_csv = Path(args.firmware_index_csv).expanduser().resolve()
    ident_priority_csv = Path(args.ident_priority_csv).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    stage_families_csv = Path(args.stage_families_csv).expanduser().resolve() if args.stage_families_csv else Path("")
    checksum_registry_json = (
        Path(args.checksum_registry_json).expanduser().resolve()
        if args.checksum_registry_json
        else out_dir / "checksum_capability_registry_v1.json"
    )

    records = read_firmware_index(firmware_index_csv)
    ident_rows = read_ident_priority(ident_priority_csv)
    stage_by_sw = read_stage_families(stage_families_csv) if stage_families_csv else {}

    if checksum_registry_json.exists():
        checksum_registry = read_checksum_registry(checksum_registry_json)
    else:
        checksum_registry = default_checksum_registry()
        checksum_registry_json.write_text(
            json.dumps(checksum_registry, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    by_sw, sw_by_ecu_counter, sw_by_brand_counter = build_firmware_aggregates(records)
    rows = build_manifest(
        ident_rows=ident_rows,
        stage_by_sw=stage_by_sw,
        by_sw=by_sw,
        sw_by_ecu_counter=sw_by_ecu_counter,
        sw_by_brand_counter=sw_by_brand_counter,
        checksum_registry=checksum_registry,
    )

    manifest_csv = out_dir / "family_manifest.csv"
    toyota_csv = out_dir / "family_manifest_toyota.csv"
    haval_csv = out_dir / "family_manifest_haval.csv"
    summary_txt = out_dir / "family_manifest_summary.txt"

    fields = [
        "target_brand",
        "family_key",
        "family_type",
        "software_id",
        "ecu_primary",
        "ecu_candidates",
        "brand_candidates",
        "doc_count",
        "stock_file_count",
        "mod_file_count",
        "stock_sha256",
        "mod_sha256",
        "size_bytes_observed",
        "role_counts",
        "stage1_ready",
        "euro2_ready",
        "default_operation",
        "readiness_score",
        "readiness_status",
        "checksum_status",
        "checksum_source",
        "safety_gate_status",
        "risk_level",
        "blockers",
        "recommended_action",
    ]
    write_csv(manifest_csv, rows, fields)
    write_csv(toyota_csv, [row for row in rows if row.get("target_brand") == "TOYOTA"], fields)
    write_csv(haval_csv, [row for row in rows if row.get("target_brand") == "HAVAL"], fields)
    write_summary(summary_txt, rows)

    print(f"rows_total={len(rows)}")
    print(f"written={manifest_csv}")
    print(f"written={toyota_csv}")
    print(f"written={haval_csv}")
    print(f"written={summary_txt}")
    print(f"written={checksum_registry_json}")


if __name__ == "__main__":
    main()
