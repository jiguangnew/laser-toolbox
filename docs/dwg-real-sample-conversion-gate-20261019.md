# Real DWG import candidate — test with customer sample (2026-10-19)

**Scope:** input adapter only; original DXF processing and production main unchanged. **Status: BLOCKED at third-party DWG decoder, not a converted drawing**.

The user supplied a private DWG (`XIADANBAN(1).dwg`, AC1032, 137549 bytes) with confirmed **3mm** material and **0.7mm** target tab. Do not commit the proprietary DWG or its thumbnails to this public repo.

A functional standalone `dwg_convert_and_audit.py` candidate with a **six-test unittest suite** was built and executed in the isolated runtime. This tool:

- Keeps the original DWG byte-for-byte unchanged with SHA256 readback.
- Supports real external `dwgread` / `dwg2dxf` (GNU LibreDWG) and ODA File Converter adapters; no fake PDF/PNG geometry fallback.
- Converts DWG to `converted_REVIEW_ONLY.dxf` only if a genuine external decoder exists and DXF passes `ezdxf` audit and contains vector entities.
- Extracts DXF entity types, layers, `INSERT` names, raw ACI/TrueColor, units and bounding box; flags unsupported geometry and units uncertainty.
- Never tags result as manufacturing-ready, since geometry/scale/color/part-by-part review remains required; 3mm tab metadata is 0.7mm.
- Fails closed without an installed decoder, on invalid DXF, and before overriding a previous output.

Regression: **six of six automated tests PASSED**, including actual customer DWG header read and unchanged SHA, blocked status with missing decoder, mocked-converter path (explicitly synthetic, not real DWG decoding), DXF color/unit audit, corrupt payload and overwrite refusal.

**Actual sample run:** `BLOCKED_NO_DWG_DECODER_AVAILABLE`, `geometry_read=false`, `cuttable=false`, no DXF produced, original SHA `bc6e3bbdb0eea3e497216be80380bc9617e3c1e5921ef39f0e2cbd252f20b91e`. The execution environment had no DWG geometry parser and blocked outbound installation via Debian/FTP/GitHub; repeated downloads were unsuccessful.

**Runnable adapter & tests package (private user Drive, not public customer data):**
https://drive.google.com/file/d/18YJlWtHIX2jKL2IUdTcIsd3IIfJA6iYx/view

**Full private customer sample and linked evidence:**
https://drive.google.com/drive/folders/1iAr35MrFjDWFq-41Qsd9zxYXZlW4koyV

Next real validation: install or provide compliant LibreDWG `dwgread` in a reachable environment, run the real DWG source through the adapter, and review entity counts, scale, colors, circles, blocks, slots and part-specific tab needs against the source before connecting the web UI. GNU LibreDWG is GPLv3+ and cannot be silently combined under incompatible commercial licensing; review ODA's permissions too. No stable or main code was modified.
