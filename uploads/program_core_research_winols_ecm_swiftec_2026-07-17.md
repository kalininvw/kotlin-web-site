# Program Core Research Notes (WinOLS / ECM Titanium / Swiftec)

Date: 2026-07-17  
Scope: architecture ideas for our own Stage1/Euro2 program (Toyota + Haval first)  
Constraint: this note captures workflow/product patterns, not binary patch algorithms.

## 1) Sources reviewed

### Official / primary
- EVC WinOLS product page: https://www.evc.de/en/product/ols/software/default.asp
- EVC WinOLS manual (PDF): https://www.evc.de/ftp/winols/WinOLS%20HelpEn.pdf
- Alientech ECM Titanium pages:
  - https://alientech-usa.com/pages/ecm-titanium
  - https://www.alientechglobal.com/ecm-titanium/
- Swiftec official pages:
  - https://www.swiftec.pt/
  - https://www.swiftec.pt/modules/checksums/
  - https://www.swiftec.pt/modules/swiftec-checksum-detection-module/
  - https://www.swiftec.pt/modules/swiftec-maps-recognition-module/
- BitSoftware module references:
  - https://bitsoftware.com/bitbox/catalog/79
  - https://bitsoftware.com/bitedit/catalog/104

### Secondary / lower confidence
- Blog/tutorial materials discussing workflow behavior and usage patterns.

## 2) Reusable product patterns (high value)

1. **Project-centric model**
   - Keep everything in a project container: source file, metadata, detected entities, map definitions, edits, validation status.
   - Do not store only “result file”; store full lineage and reproducibility data.

2. **Map definition portability**
   - WinOLS-like concept: lightweight map-definition pack (structure only, no map values).
   - Benefit: transfer tuning structure between close software variants and teams.

3. **Checksum capability registry**
   - Registry per ECU/software family: whether checksum can be corrected by our pipeline/toolchain.
   - Explicit gating before export/write stage.

4. **ID-first workflow**
   - The program should classify by ID/BL/SW/HW/ECU first, then route to template family.
   - This matches our current `ident_docs_ingest + stage_core_builder` direction.

5. **Operation templates with validation gate**
   - Operation = `stage1` or `euro2`
   - Required checks before “ready”: family consistency, size compatibility, checksum availability, diff-scope sanity.

6. **Catalog-wide alias normalization**
   - Normalize labels globally (`stage1`, `stage 1`, `st1`, `euro2`, `e2`, etc.).
   - No brand-specific dialog hacks; rules must generalize across the catalog.

## 3) Practical decisions for our program core

1. Keep current pipeline split:
   - `firmware_catalog_ingest.py` -> normalized firmware index
   - `ident_docs_ingest.py` -> ID/BL/SW/HW extraction + Toyota/Haval priority lists
   - `stage_core_builder.py` -> readiness + operation matrix + roadmap

2. Treat **Euro2 as first-class operation**
   - Already embedded into operation matrix and default operation routing.

3. Continue with **Toyota/Haval first wave**
   - Toyota route: software-family driven (`89663-*` clusters)
   - Haval route: ECU-family driven (`MG1U*`) + software IDs when available

4. Build a unified “family manifest” next
   - one row per family with:
     - canonical keys (brand/ecu/sw/bl/hw)
     - available stock/mod references
     - operation readiness (`stage1_ready`, `euro2_ready`)
     - checksum readiness

## 4) What not to copy directly

- Vendor-locked licensing and dongle logic are business mechanisms, not technical necessities for our core.
- “One-click” claims without transparent validation are risky; our pipeline should remain auditable and deterministic.

## 5) Current status after research

- We already have the base architecture to absorb these patterns.
- Main next technical step: implement `family_manifest_builder` and checksum-capability registry merge into roadmap scoring.
