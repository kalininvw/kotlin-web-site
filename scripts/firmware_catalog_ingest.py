#!/usr/bin/env python3
"""
Build a normalized firmware catalog index from a local folder
(for example, a synced Yandex Disk directory).

The script does not modify firmware binaries. It only extracts metadata,
normalizes tokens, and prepares a structured dataset for downstream logic.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


FIRMWARE_EXTENSIONS = {
    ".bin",
    ".ori",
    ".mod",
    ".hex",
    ".sgo",
    ".frf",
    ".rar",
    ".zip",
    ".7z",
}

BINARY_EXTENSIONS = {
    ".bin",
    ".ori",
    ".mod",
    ".hex",
    ".sgo",
    ".frf",
}

SOFTWARE_PATTERNS: Sequence[re.Pattern[str]] = (
    re.compile(r"(?<![A-Z0-9])89663-[A-Z0-9]{3,6}(?:-[A-Z0-9]{1,3})?(?![A-Z0-9])", re.IGNORECASE),
    re.compile(r"(?<![A-Z0-9])89661-[A-Z0-9]{3,6}(?:-[A-Z0-9]{1,3})?(?![A-Z0-9])", re.IGNORECASE),
    re.compile(r"(?<![A-Z0-9])F01R[0-9A-Z]{6,10}(?![A-Z0-9])", re.IGNORECASE),
    re.compile(r"(?<![A-Z0-9])3600010-[A-Z0-9]{4,8}(?![A-Z0-9])", re.IGNORECASE),
)
ECU_RE = re.compile(
    r"(?<![A-Z0-9])("
    r"MG1US008|MG1UA008|MG1US708|ME17\.8\.10|ME17\.8\.8|ME17U6|MED17\.8\.10|"
    r"MT20U|MT22(?:\.1|U)?|MT92(?:\.1)?|DCM\s*7\.1AP|EDC17[ACP0-9]*"
    r")(?![A-Z0-9])",
    re.IGNORECASE,
)
BRAND_RE = re.compile(
    r"(?<![A-Z0-9])("
    r"HAVAL|GREAT[-_\s]?WALL|CHERY|EXEED|JAC|GEELY|CHANGAN|GAC|DONGFENG|FAW|BAIC|SAIC|WEY|TANK"
    r")(?![A-Z0-9])",
    re.IGNORECASE,
)


FEATURE_ALIASES: Dict[str, Sequence[str]] = {
    "stage1": ("stage1", "stage 1", "st1", "tune1", "rt47 stage1", "modrt47 stage1"),
    "euro2": ("euro2", "euro 2", "euro-2", "евро2", "евро 2", "e2", "mod e2"),
    "stock": ("stock", "stok", "сток", "ori", "original"),
    "mod": ("mod", "modified", "тюнинг", "tuned"),
    "rt47": ("rt47", "modrt47"),
}


def normalize_text(value: str) -> str:
    value = value.lower().replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", value).strip()


def infer_features(raw_name: str) -> List[str]:
    normalized = normalize_text(raw_name)
    found: List[str] = []
    for feature, aliases in FEATURE_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                found.append(feature)
                break
    return sorted(set(found))


def sha256sum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_candidates(pattern: re.Pattern[str], text: str) -> List[str]:
    matches = [m.group(0) for m in pattern.finditer(text)]
    unique = sorted({m.upper() for m in matches})
    return unique


def parse_software_candidates(text: str) -> List[str]:
    values: List[str] = []
    for pattern in SOFTWARE_PATTERNS:
        values.extend(m.group(0) for m in pattern.finditer(text))
    return sorted({v.upper() for v in values})


@dataclass
class FirmwareRecord:
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

    def to_row(self) -> Dict[str, str]:
        return {
            "rel_path": self.rel_path,
            "file_name": self.file_name,
            "extension": self.extension,
            "size_bytes": str(self.size_bytes),
            "sha256": self.sha256,
            "ecu_candidates": "|".join(self.ecu_candidates),
            "brand_candidates": "|".join(self.brand_candidates),
            "software_candidates": "|".join(self.software_candidates),
            "features": "|".join(self.features),
            "inferred_role": self.inferred_role,
        }


def infer_role(features: Sequence[str]) -> str:
    feature_set = set(features)
    if "stock" in feature_set and "mod" not in feature_set and "stage1" not in feature_set and "euro2" not in feature_set:
        return "stock"
    if "stage1" in feature_set or "euro2" in feature_set or "mod" in feature_set:
        return "modified"
    return "unknown"


def collect_firmware_files(root: Path) -> List[Path]:
    files: List[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in FIRMWARE_EXTENSIONS:
            files.append(path)
    return sorted(files)


def build_records(root: Path, files: Iterable[Path]) -> List[FirmwareRecord]:
    records: List[FirmwareRecord] = []
    for path in files:
        rel = str(path.relative_to(root))
        name = path.name
        text = normalize_text(name)
        features = infer_features(name)
        role = infer_role(features)
        records.append(
            FirmwareRecord(
                rel_path=rel,
                file_name=name,
                extension=path.suffix.lower(),
                size_bytes=path.stat().st_size,
                sha256=sha256sum(path),
                ecu_candidates=parse_candidates(ECU_RE, name),
                brand_candidates=parse_candidates(BRAND_RE, name),
                software_candidates=parse_software_candidates(name),
                features=features,
                inferred_role=role,
            )
        )
    apply_secondary_role_inference(records)
    return records


def link_stock_to_mod(records: Sequence[FirmwareRecord]) -> List[Dict[str, str]]:
    """
    Pair likely stock/mod files with shared software IDs and close size.
    This is a heuristic for dataset organization, not calibration logic.
    """
    by_sw: Dict[str, List[FirmwareRecord]] = {}
    for record in records:
        for sw in record.software_candidates:
            by_sw.setdefault(sw, []).append(record)

    pairs: List[Dict[str, str]] = []
    for sw, group in by_sw.items():
        stocks = [
            r
            for r in group
            if r.extension in BINARY_EXTENSIONS and r.inferred_role in {"stock", "stock_inferred"}
        ]
        mods = [r for r in group if r.extension in BINARY_EXTENSIONS and r.inferred_role == "modified"]
        if not stocks or not mods:
            continue
        for stock in stocks:
            for mod in mods:
                delta = abs(stock.size_bytes - mod.size_bytes)
                if delta <= 8192:
                    pairs.append(
                        {
                            "software_id": sw,
                            "stock_rel_path": stock.rel_path,
                            "stock_sha256": stock.sha256,
                            "mod_rel_path": mod.rel_path,
                            "mod_sha256": mod.sha256,
                            "size_delta_bytes": str(delta),
                            "shared_ecu": "|".join(sorted(set(stock.ecu_candidates) & set(mod.ecu_candidates))),
                            "shared_brand": "|".join(sorted(set(stock.brand_candidates) & set(mod.brand_candidates))),
                            "mod_features": "|".join(mod.features),
                        }
                    )
    return pairs


def apply_secondary_role_inference(records: Sequence[FirmwareRecord]) -> None:
    """
    If a software family has explicit modified files and another binary file
    with the same software id has no modification labels, mark it as stock_inferred.
    """
    by_sw: Dict[str, List[FirmwareRecord]] = {}
    for record in records:
        for sw in record.software_candidates:
            by_sw.setdefault(sw, []).append(record)

    for sw, group in by_sw.items():
        has_modified = any(r.inferred_role == "modified" and r.extension in BINARY_EXTENSIONS for r in group)
        if not has_modified:
            continue
        for record in group:
            if record.extension not in BINARY_EXTENSIONS:
                continue
            if record.inferred_role != "unknown":
                continue
            if record.features:
                continue
            record.inferred_role = "stock_inferred"


def write_csv(path: Path, rows: Sequence[Dict[str, str]], fieldnames: Sequence[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(path: Path, root: Path, records: Sequence[FirmwareRecord], pairs: Sequence[Dict[str, str]]) -> None:
    role_counts: Dict[str, int] = {}
    ecu_counts: Dict[str, int] = {}
    feature_counts: Dict[str, int] = {}
    for record in records:
        role_counts[record.inferred_role] = role_counts.get(record.inferred_role, 0) + 1
        for ecu in record.ecu_candidates:
            ecu_counts[ecu] = ecu_counts.get(ecu, 0) + 1
        for feature in record.features:
            feature_counts[feature] = feature_counts.get(feature, 0) + 1

    top_ecu = sorted(ecu_counts.items(), key=lambda item: item[1], reverse=True)[:15]
    top_feat = sorted(feature_counts.items(), key=lambda item: item[1], reverse=True)

    lines: List[str] = [
        "Firmware catalog ingest summary",
        f"source_root={root}",
        f"files_indexed={len(records)}",
        f"candidate_stock_mod_pairs={len(pairs)}",
        "role_counts:",
    ]
    for role, count in sorted(role_counts.items()):
        lines.append(f"  {role}: {count}")
    lines.append("top_ecu_candidates:")
    for ecu, count in top_ecu:
        lines.append(f"  {ecu}: {count}")
    lines.append("feature_counts:")
    for feature, count in top_feat:
        lines.append(f"  {feature}: {count}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Index firmware files from local folder (e.g., Yandex Disk sync)."
    )
    parser.add_argument("--source", required=True, help="Path to firmware folder.")
    parser.add_argument(
        "--out-dir",
        required=True,
        help="Output directory for generated CSV/JSON/TXT files.",
    )
    args = parser.parse_args()

    source = Path(args.source).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not source.exists() or not source.is_dir():
        raise SystemExit(f"Source folder not found or not a directory: {source}")

    files = collect_firmware_files(source)
    records = build_records(source, files)
    pairs = link_stock_to_mod(records)

    index_rows = [record.to_row() for record in records]
    index_csv = out_dir / "firmware_catalog_index.csv"
    pair_csv = out_dir / "firmware_catalog_stock_mod_pairs.csv"
    rules_json = out_dir / "firmware_catalog_feature_aliases.json"
    summary_txt = out_dir / "firmware_catalog_ingest_summary.txt"

    write_csv(
        index_csv,
        index_rows,
        [
            "rel_path",
            "file_name",
            "extension",
            "size_bytes",
            "sha256",
            "ecu_candidates",
            "brand_candidates",
            "software_candidates",
            "features",
            "inferred_role",
        ],
    )
    write_csv(
        pair_csv,
        pairs,
        [
            "software_id",
            "stock_rel_path",
            "stock_sha256",
            "mod_rel_path",
            "mod_sha256",
            "size_delta_bytes",
            "shared_ecu",
            "shared_brand",
            "mod_features",
        ],
    )
    rules_json.write_text(
        json.dumps(
            {
                "normalization": {
                    "lowercase": True,
                    "replace_dash_underscore": True,
                    "collapse_spaces": True,
                },
                "feature_aliases": FEATURE_ALIASES,
                "notes": [
                    "Systemic aliases; do not create brand-specific dialog hacks.",
                    "This file classifies labels only and does not implement binary patching.",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    write_summary(summary_txt, source, records, pairs)

    print(f"indexed_files={len(records)}")
    print(f"stock_mod_pairs={len(pairs)}")
    print(f"written={index_csv}")
    print(f"written={pair_csv}")
    print(f"written={rules_json}")
    print(f"written={summary_txt}")


if __name__ == "__main__":
    main()
