# Vector import candidate (2026-10-19)

Status: **TESTED LOCALLY, NOT INTEGRATED, NOT PRODUCTION**.

Users must be able to upload their original DWG, DXF, AI, SVG or vector PDF, without manual DXF pre-conversion. This is a new, isolated input-adapter requirement: existing `auto_tab.py` and the stable web route are unchanged.

A standalone Python candidate `vector_import.py`, source, tests, and Chinese README are in the project Drive package:
https://drive.google.com/file/d/1ZpftsdqVal8ORx7ji8WYQvRKPOSk1J6s/view

Synthetic smoke tests: **7/7 passed**. DXF audited and byte-preserved; SVG + one-page vector PDF imported as polylines with millimetre dimensions and TrueColor; PDF-compatible AI signature and PostScript EPS smoke-tested. Raster PDF and multi-page PDF fail closed. Output is labelled `converted_REVIEW_ONLY.dxf` with ACI 8, never auto-cut or auto-tab. Imported filled paths, curves, text, clipping, scale, groups, and machining colors require customer sample review.

**DWG not yet usable here**: candidate calls external ODA File Converter if installed, but ODA is absent and real DWG input was not tested. Official ODA material restricts nonmember free use to noncommercial applications; do not redistribute this converter as a public commercial service without a licensing decision. Candidate PyMuPDF dependency is AGPL/commercial; clarify final product licensing before releasing. CDR and non-PDF-compatible Illustrator native sources remain unsupported.

Next verified goal: obtain actual customer DWG + AI/SVG/PDF, validate 1:1 dimensions and per-entity color/contour/layer integrity, and only then integrate into an isolated upload/preflight endpoint. Do not touch production `main` or existing tab algorithm.
