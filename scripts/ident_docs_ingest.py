#!/usr/bin/env python3
"""
Index identification documents (id/bl/sw/ident) from a local folder and
build structured hints for Stage1 core preparation.

This script is read-only for source files.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple


TEXT_EXTENSIONS = {
    ".txt",
    ".csv",
    ".log",
    ".ini",
    ".xml",
    ".json",
    ".html",
    ".htm",
    ".md",
}

DOC_NAME_STRICT_RE = re.compile(r"(^|[_\-\s])(id|ident|sw|bl|hw|ecu)([_\-\s]|$)", re.IGNORECASE)
DOC_NAME_RELAXED_RE = re.compile(r"(id|ident|sw|bl|hw|ecu)", re.IGNORECASE)

BRAND_RE = re.compile(
    r"(?<![A-Z0-9])("
    r"TOYOTA|LEXUS|HAVAL|GREAT[-_\s]?WALL|WEY|TANK|CHERY|EXEED|JAC|GEELY|CHANGAN|GAC|DONGFENG|FAW|BAIC|SAIC"
    r")(?![A-Z0-9])",
    re.IGNORECASE,
)
ECU_RE = re.compile(
    r"(?<![A-Z0-9])("
    r"MG1US008|MG1UA008|MG1US708|ME17\.8\.10|ME17\.8\.8|ME17U6|MED17\.8\.10|"
    r"MT20U|MT22(?:\.1|U)?|MT92(?:\.1)?|DCM\s*7\.1AP|EDC17[ACP0-9]*"
    r")(?![A-Z0-9])",
    re.IGNORECASE,
)

SW_PATTERNS: Sequence[re.Pattern[str]] = (
    re.compile(r"(?<![A-Z0-9])89663-[A-Z0-9]{3,6}(?:-[A-Z0-9]{1,3})?(?![A-Z0-9])", re.IGNORECASE),
    re.compile(r"(?<![A-Z0-9])89661-[A-Z0-9]{3,6}(?:-[A-Z0-9]{1,3})?(?![A-Z0-9])", re.IGNORECASE),
    re.compile(r"(?<![A-Z0-9])F01R[0-9A-Z]{6,10}(?![A-Z0-9])", re.IGNORECASE),
    re.compile(r"(?<![A-Z0-9])3600010-[A-Z0-9]{4,8}(?![A-Z0-9])", re.IGNORECASE),
    re.compile(r"(?<![A-Z0-9])Z[0-9A-Z]{9,11}(?![A-Z0-9])", re.IGNORECASE),
)

BL_PATTERNS: Sequence[re.Pattern[str]] = (
    re.compile(r"\bBL(?:\s*ID)?\s*[:=]\s*([A-Z0-9._\-]{4,})", re.IGNORECASE),
    re.compile(r"\bBOOT(?:LOADER)?\s*[:=]\s*([A-Z0-9._\-]{4,})", re.IGNORECASE),
)

HW_PATTERNS: Sequence[re.Pattern[str]] = (
    re.compile(r"\bHW(?:\s*ID)?\s*[:=]\s*([A-Z0-9._\-]{4,})", re.IGNORECASE),
    re.compile(r"\bHARDWARE\s*[:=]\s*([A-Z0-9._\-]{4,})", re.IGNORECASE),
)

SW_KEY_PATTERNS: Sequence[re.Pattern[str]] = (
    re.compile(r"\bSW(?:\s*ID)?\s*[:=]\s*([A-Z0-9._\-]{4,})", re.IGNORECASE),
    re.compile(r"\bSOFTWARE\s*[:=]\s*([A-Z0-9._\-]{4,})", re.IGNORECASE),
)

PATH_BRAND_ALIASES: Dict[str, str] = {
    "toyota": "TOYOTA",
    "lexus": "TOYOTA",
    "haval": "HAVAL",
    "greatwall": "HAVAL",
    "great": "HAVAL",
    "wall": "HAVAL",
    "wey": "HAVAL",
    "tank": "HAVAL",
    "chery": "CHERY",
    "exeed": "EXEED",
    "jac": "JAC",
    "geely": "GEELY",
    "changan": "CHANGAN",
    "gac": "GAC",
    "dongfeng": "DONGFENG",
    "faw": "FAW",
    "baic": "BAIC",
    "saic": "SAIC",
}


def unique_sorted(values: Iterable[str]) -> List[str]:
    return sorted({value.upper() for value in values if value})


def parse_by_patterns(text: str, patterns: Sequence[re.Pattern[str]], group: int = 0) -> List[str]:
    results: List[str] = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            results.append(match.group(group))
    return unique_sorted(results)


def parse_sw_ids(text: str) -> List[str]:
    return parse_by_patterns(text, SW_PATTERNS, 0)


def parse_brand_hints_from_path(rel_path: str) -> List[str]:
    lowered = rel_path.lower().replace("\\", "/")
    chunks = re.split(r"[/_\-\s\.]+", lowered)
    hints: List[str] = []
    for chunk in chunks:
        if not chunk:
            continue
        mapped = PATH_BRAND_ALIASES.get(chunk)
        if mapped:
            hints.append(mapped)
    return unique_sorted(hints)


def choose_name_filter(name_mode: str) -> Optional[re.Pattern[str]]:
    if name_mode == "all":
        return None
    if name_mode == "relaxed":
        return DOC_NAME_RELAXED_RE
    return DOC_NAME_STRICT_RE


def read_text_limited(path: Path, max_chars: int) -> str:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    if len(raw) <= max_chars:
        return raw
    return raw[:max_chars]


@dataclass
class DocRecord:
    rel_path: str
    file_name: str
    extension: str
    size_bytes: int
    software_ids: List[str]
    bootloader_ids: List[str]
    hardware_ids: List[str]
    ecu_candidates: List[str]
    brand_candidates: List[str]
    path_brand_hints: List[str]

    def row(self) -> Dict[str, str]:
        return {
            "rel_path": self.rel_path,
            "file_name": self.file_name,
            "extension": self.extension,
            "size_bytes": str(self.size_bytes),
            "software_ids": "|".join(self.software_ids),
            "bootloader_ids": "|".join(self.bootloader_ids),
            "hardware_ids": "|".join(self.hardware_ids),
            "ecu_candidates": "|".join(self.ecu_candidates),
            "brand_candidates": "|".join(self.brand_candidates),
            "path_brand_hints": "|".join(self.path_brand_hints),
        }


def collect_docs(source: Path, name_mode: str, max_file_size_mb: int) -> List[Path]:
    name_filter = choose_name_filter(name_mode)
    max_size = max_file_size_mb * 1024 * 1024
    docs: List[Path] = []
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        if path.stat().st_size > max_size:
            continue
        if name_filter is not None and not name_filter.search(path.name):
            continue
        docs.append(path)
    return sorted(docs)


def parse_docs(source: Path, docs: Sequence[Path], max_chars: int) -> List[DocRecord]:
    records: List[DocRecord] = []
    for path in docs:
        rel_path = str(path.relative_to(source))
        path_brand_hints = parse_brand_hints_from_path(rel_path)
        text = read_text_limited(path, max_chars=max_chars)
        merged = "\n".join([rel_path, path.name, text])
        sw_values = unique_sorted(parse_sw_ids(merged) + parse_by_patterns(merged, SW_KEY_PATTERNS, 1))
        bl_values = parse_by_patterns(merged, BL_PATTERNS, 1)
        hw_values = parse_by_patterns(merged, HW_PATTERNS, 1)
        ecus = parse_by_patterns(merged, (ECU_RE,), 0)
        brands = unique_sorted(parse_by_patterns(merged, (BRAND_RE,), 0) + path_brand_hints)
        records.append(
            DocRecord(
                rel_path=rel_path,
                file_name=path.name,
                extension=path.suffix.lower(),
                size_bytes=path.stat().st_size,
                software_ids=sw_values,
                bootloader_ids=bl_values,
                hardware_ids=hw_values,
                ecu_candidates=ecus,
                brand_candidates=brands,
                path_brand_hints=path_brand_hints,
            )
        )
    return records


def write_csv(path: Path, rows: Sequence[Dict[str, str]], fieldnames: Sequence[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_firmware_index(path: Path) -> Dict[str, Dict[str, Set[str]]]:
    """
    Return by software id: features, ecu, brands, roles, file_count.
    """
    data: Dict[str, Dict[str, Set[str]]] = {}
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            sw_ids = [v for v in row.get("software_candidates", "").split("|") if v]
            if not sw_ids:
                continue
            for sw in sw_ids:
                slot = data.setdefault(
                    sw,
                    {
                        "features": set(),
                        "ecus": set(),
                        "brands": set(),
                        "roles": set(),
                        "files": set(),
                    },
                )
                slot["features"].update(v for v in row.get("features", "").split("|") if v)
                slot["ecus"].update(v for v in row.get("ecu_candidates", "").split("|") if v)
                slot["brands"].update(v for v in row.get("brand_candidates", "").split("|") if v)
                role = row.get("inferred_role", "")
                if role:
                    slot["roles"].add(role)
                slot["files"].add(row.get("rel_path", ""))
    return data


def build_family_hints(
    records: Sequence[DocRecord],
    firmware_sw: Dict[str, Dict[str, Set[str]]],
) -> List[Dict[str, str]]:
    by_family: Dict[str, Dict[str, Set[str] | str]] = {}
    for record in records:
        if record.software_ids:
            keys = [f"SW:{sw}" for sw in record.software_ids]
        elif record.ecu_candidates:
            keys = [f"ECU:{ecu}" for ecu in record.ecu_candidates]
        else:
            keys = []

        for key in keys:
            slot = by_family.setdefault(
                key,
                {
                    "family_key": key,
                    "family_type": "software" if key.startswith("SW:") else "ecu",
                    "software_id": key[3:] if key.startswith("SW:") else "",
                    "ecu_primary": key[4:] if key.startswith("ECU:") else "",
                    "docs": set(),
                    "bl": set(),
                    "hw": set(),
                    "ecu": set(),
                    "brand": set(),
                },
            )
            slot["docs"].add(record.rel_path)  # type: ignore[index]
            slot["bl"].update(record.bootloader_ids)  # type: ignore[index]
            slot["hw"].update(record.hardware_ids)  # type: ignore[index]
            slot["ecu"].update(record.ecu_candidates)  # type: ignore[index]
            slot["brand"].update(record.brand_candidates)  # type: ignore[index]

    rows: List[Dict[str, str]] = []
    for key, values in sorted(by_family.items()):
        sw = str(values["software_id"])
        fw = firmware_sw.get(sw, {}) if sw else {}
        fw_features = sorted(fw.get("features", set()))
        fw_ecu = sorted(fw.get("ecus", set()))
        fw_brands = sorted(fw.get("brands", set()))
        fw_roles = sorted(fw.get("roles", set()))
        fw_files = fw.get("files", set())
        merged_brands = sorted(set(values["brand"]) | set(fw_brands))  # type: ignore[arg-type]
        merged_ecu = sorted(set(values["ecu"]) | set(fw_ecu))  # type: ignore[arg-type]
        ecu_primary = str(values["ecu_primary"]) or (merged_ecu[0] if merged_ecu else "")

        rows.append(
            {
                "family_key": str(values["family_key"]),
                "family_type": str(values["family_type"]),
                "software_id": sw,
                "ecu_primary": ecu_primary,
                "doc_count": str(len(values["docs"])),  # type: ignore[arg-type]
                "doc_paths": "|".join(sorted(values["docs"])),  # type: ignore[arg-type]
                "bootloader_ids": "|".join(sorted(values["bl"])),  # type: ignore[arg-type]
                "hardware_ids": "|".join(sorted(values["hw"])),  # type: ignore[arg-type]
                "ecu_candidates": "|".join(merged_ecu),
                "brand_candidates": "|".join(merged_brands),
                "firmware_features": "|".join(fw_features),
                "firmware_roles": "|".join(fw_roles),
                "firmware_file_count": str(len(fw_files)),
            }
        )
    return rows


def infer_brand_priorities(sw: str, brands: Set[str], ecus: Set[str]) -> List[Tuple[str, str]]:
    upper_brands = {brand.upper().replace("_", " ").replace("-", " ").strip() for brand in brands}
    has_toyota = bool({"TOYOTA", "LEXUS"} & upper_brands)
    has_haval = bool({"HAVAL", "GREAT WALL", "WEY", "TANK"} & upper_brands)
    has_mg1u = any(ecu.startswith("MG1U") for ecu in ecus)
    multi_brand_catalog = len(upper_brands) >= 8

    priorities: List[Tuple[str, str]] = []
    if sw.startswith("89663-") or sw.startswith("89661-"):
        priorities.append(("TOYOTA", "software_prefix_heuristic"))

    if multi_brand_catalog and has_mg1u and has_haval:
        priorities.append(("HAVAL", "multi_brand_catalog_ecu_heuristic"))
    else:
        if has_toyota:
            priorities.append(("TOYOTA", "brand_explicit"))
        if has_haval:
            priorities.append(("HAVAL", "brand_explicit"))

    if not priorities and has_mg1u:
        priorities.append(("HAVAL", "ecu_family_heuristic"))

    if not priorities:
        priorities.append(("OTHER", "insufficient_brand_data"))

    unique: List[Tuple[str, str]] = []
    seen: Set[Tuple[str, str]] = set()
    for item in priorities:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def build_priority_rows(family_rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    source_rank = {
        "brand_explicit": 1,
        "software_prefix_heuristic": 2,
        "multi_brand_catalog_ecu_heuristic": 3,
        "ecu_family_heuristic": 4,
        "insufficient_brand_data": 99,
    }
    rows: List[Dict[str, str]] = []
    for row in family_rows:
        brands = {v for v in row.get("brand_candidates", "").split("|") if v}
        ecus = {v for v in row.get("ecu_candidates", "").split("|") if v}
        software_id = row.get("software_id", "")
        targets = infer_brand_priorities(software_id, brands, ecus)
        best_by_target: Dict[str, str] = {}
        for target_brand, source in targets:
            if target_brand not in {"TOYOTA", "HAVAL"}:
                continue
            current = best_by_target.get(target_brand)
            if current is None or source_rank.get(source, 50) < source_rank.get(current, 50):
                best_by_target[target_brand] = source
        for target_brand, source in sorted(best_by_target.items()):
            if target_brand == "HAVAL":
                if not (any(ecu.startswith("MG1U") for ecu in ecus) or "MG1U" in row.get("family_key", "").upper()):
                    continue
            if target_brand == "TOYOTA":
                sw_upper = software_id.upper()
                if not (
                    sw_upper.startswith("89663-")
                    or sw_upper.startswith("89661-")
                    or "TOYOTA" in {v.upper() for v in brands}
                    or "LEXUS" in {v.upper() for v in brands}
                ):
                    continue
            rows.append(
                {
                    "target_brand": target_brand,
                    "priority_source": source,
                    "family_key": row.get("family_key", ""),
                    "family_type": row.get("family_type", ""),
                    "software_id": software_id,
                    "ecu_primary": row.get("ecu_primary", ""),
                    "ecu_candidates": row.get("ecu_candidates", ""),
                    "brand_candidates": row.get("brand_candidates", ""),
                    "bootloader_ids": row.get("bootloader_ids", ""),
                    "hardware_ids": row.get("hardware_ids", ""),
                    "firmware_features": row.get("firmware_features", ""),
                    "firmware_roles": row.get("firmware_roles", ""),
                    "firmware_file_count": row.get("firmware_file_count", "0"),
                    "doc_count": row.get("doc_count", "0"),
                    "next_action": "collect-stock-and-mod-binaries-if-missing",
                }
            )
    return sorted(rows, key=lambda item: (item["target_brand"], item.get("software_id", ""), item.get("family_key", "")))


def build_entities_flat(records: Sequence[DocRecord]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for record in records:
        for sw in record.software_ids:
            rows.append({"entity_type": "software_id", "value": sw, "rel_path": record.rel_path})
        for bl in record.bootloader_ids:
            rows.append({"entity_type": "bootloader_id", "value": bl, "rel_path": record.rel_path})
        for hw in record.hardware_ids:
            rows.append({"entity_type": "hardware_id", "value": hw, "rel_path": record.rel_path})
        for ecu in record.ecu_candidates:
            rows.append({"entity_type": "ecu", "value": ecu, "rel_path": record.rel_path})
        for brand in record.brand_candidates:
            rows.append({"entity_type": "brand", "value": brand, "rel_path": record.rel_path})
    return rows


def write_summary(
    path: Path,
    source: Path,
    records: Sequence[DocRecord],
    family_rows: Sequence[Dict[str, str]],
    priority_rows: Sequence[Dict[str, str]],
) -> None:
    toyota = sum(1 for item in priority_rows if item["target_brand"] == "TOYOTA")
    haval = sum(1 for item in priority_rows if item["target_brand"] == "HAVAL")
    lines = [
        "Identification docs ingest summary",
        f"source_root={source}",
        f"docs_indexed={len(records)}",
        f"software_families={len(family_rows)}",
        f"priority_toyota={toyota}",
        f"priority_haval={haval}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest identification documents from local folder.")
    parser.add_argument("--source", required=True, help="Root folder with docs.")
    parser.add_argument("--out-dir", required=True, help="Output folder.")
    parser.add_argument(
        "--name-mode",
        choices=["strict", "relaxed", "all"],
        default="strict",
        help="strict: id/bl/sw tokens as standalone words, relaxed: token anywhere in name, all: parse all text files",
    )
    parser.add_argument(
        "--max-file-size-mb",
        type=int,
        default=8,
        help="Skip text files larger than this threshold.",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=300000,
        help="Max text chars to parse per file.",
    )
    parser.add_argument(
        "--firmware-index-csv",
        default="",
        help="Optional firmware_catalog_index.csv for enrichment.",
    )
    args = parser.parse_args()

    source = Path(args.source).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not source.exists() or not source.is_dir():
        raise SystemExit(f"Source folder not found: {source}")

    docs = collect_docs(source, name_mode=args.name_mode, max_file_size_mb=args.max_file_size_mb)
    records = parse_docs(source, docs, max_chars=args.max_chars)

    firmware_sw: Dict[str, Dict[str, Set[str]]] = {}
    if args.firmware_index_csv:
        fw_path = Path(args.firmware_index_csv).expanduser().resolve()
        if fw_path.exists():
            firmware_sw = read_firmware_index(fw_path)

    family_rows = build_family_hints(records, firmware_sw=firmware_sw)
    priority_rows = build_priority_rows(family_rows)
    entities_rows = build_entities_flat(records)

    docs_csv = out_dir / "ident_docs_index.csv"
    family_csv = out_dir / "ident_family_hints.csv"
    priority_csv = out_dir / "ident_brand_priority_toyota_haval.csv"
    priority_toyota_csv = out_dir / "ident_priority_toyota.csv"
    priority_haval_csv = out_dir / "ident_priority_haval.csv"
    entities_csv = out_dir / "ident_entities_flat.csv"
    summary_txt = out_dir / "ident_ingest_summary.txt"
    config_json = out_dir / "ident_ingest_config.json"

    write_csv(
        docs_csv,
        [item.row() for item in records],
        [
            "rel_path",
            "file_name",
            "extension",
            "size_bytes",
            "software_ids",
            "bootloader_ids",
            "hardware_ids",
            "ecu_candidates",
            "brand_candidates",
            "path_brand_hints",
        ],
    )
    write_csv(
        family_csv,
        family_rows,
        [
            "family_key",
            "family_type",
            "software_id",
            "ecu_primary",
            "doc_count",
            "doc_paths",
            "bootloader_ids",
            "hardware_ids",
            "ecu_candidates",
            "brand_candidates",
            "firmware_features",
            "firmware_roles",
            "firmware_file_count",
        ],
    )
    write_csv(
        priority_csv,
        priority_rows,
        [
            "target_brand",
            "priority_source",
            "family_key",
            "family_type",
            "software_id",
            "ecu_primary",
            "ecu_candidates",
            "brand_candidates",
            "bootloader_ids",
            "hardware_ids",
            "firmware_features",
            "firmware_roles",
            "firmware_file_count",
            "doc_count",
            "next_action",
        ],
    )
    write_csv(
        priority_toyota_csv,
        [row for row in priority_rows if row.get("target_brand") == "TOYOTA"],
        [
            "target_brand",
            "priority_source",
            "family_key",
            "family_type",
            "software_id",
            "ecu_primary",
            "ecu_candidates",
            "brand_candidates",
            "bootloader_ids",
            "hardware_ids",
            "firmware_features",
            "firmware_roles",
            "firmware_file_count",
            "doc_count",
            "next_action",
        ],
    )
    write_csv(
        priority_haval_csv,
        [row for row in priority_rows if row.get("target_brand") == "HAVAL"],
        [
            "target_brand",
            "priority_source",
            "family_key",
            "family_type",
            "software_id",
            "ecu_primary",
            "ecu_candidates",
            "brand_candidates",
            "bootloader_ids",
            "hardware_ids",
            "firmware_features",
            "firmware_roles",
            "firmware_file_count",
            "doc_count",
            "next_action",
        ],
    )
    write_csv(
        entities_csv,
        entities_rows,
        ["entity_type", "value", "rel_path"],
    )
    write_summary(summary_txt, source, records, family_rows, priority_rows)
    config_json.write_text(
        json.dumps(
            {
                "name_mode": args.name_mode,
                "max_file_size_mb": args.max_file_size_mb,
                "max_chars": args.max_chars,
                "notes": [
                    "Read-only source processing.",
                    "Toyota/Haval priority list is based on explicit brand match first, then heuristics.",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"docs_indexed={len(records)}")
    print(f"software_families={len(family_rows)}")
    print(f"priority_rows={len(priority_rows)}")
    print(f"written={docs_csv}")
    print(f"written={family_csv}")
    print(f"written={priority_csv}")
    print(f"written={priority_toyota_csv}")
    print(f"written={priority_haval_csv}")
    print(f"written={entities_csv}")
    print(f"written={summary_txt}")
    print(f"written={config_json}")


if __name__ == "__main__":
    main()
