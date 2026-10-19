#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DWG read-only preflight: header and embedded PNG only. NO DWG geometry decoded.

This is diagnostic evidence, not a DWG to DXF converter, and never passes
a file for laser cutting. It does not import production auto_tab.py.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import struct
import zlib
from pathlib import Path

DWG_FORMATS = {
    "AC1021": "DWG 2007",
    "AC1024": "DWG 2010",
    "AC1027": "DWG 2013",
    "AC1032": "DWG 2018",
}
PNG = b"\x89PNG\r\n\x1a\n"


def _validated_png(raw: bytes, start: int):
    """Reject truncated/corrupted PNGs and unreasonable chunk sizes."""
    from PIL import Image
    if raw[start:start + 8] != PNG:
        return None
    offset = start + 8
    dims = None
    try:
        for _ in range(10000):
            if offset + 12 > len(raw):
                return None
            count = struct.unpack(">I", raw[offset:offset + 4])[0]
            kind = raw[offset + 4:offset + 8]
            end = offset + 12 + count
            if count > 16_777_216 or end > len(raw):
                return None
            blob = raw[offset + 4:offset + 8 + count]
            crc = struct.unpack(">I", raw[offset + 8 + count:end])[0]
            if zlib.crc32(blob) & 0xFFFFFFFF != crc:
                return None
            if kind == b"IHDR":
                dims = struct.unpack(">II", raw[offset + 8:offset + 16])
                if 0 in dims or max(dims) > 20000:
                    return None
            offset = end
            if kind == b"IEND":
                payload = raw[start:offset]
                with Image.open(io.BytesIO(payload)) as picture:
                    picture.verify()
                return payload, dims
    except (OSError, ValueError, struct.error):
        return None
    return None


def inspect_dwg(source: Path, dest: Path) -> dict:
    from PIL import Image
    source, dest = Path(source), Path(dest)
    data = source.read_bytes()
    dest.mkdir(parents=True, exist_ok=True)
    header = data[:6].decode("ascii", errors="replace")
    report = {
        "filename": source.name,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "dwg_signature": header,
        "dwg_format": DWG_FORMATS.get(header, "UNKNOWN"),
        "geometry_decoded": False,
        "layers_checked": False,
        "colors_checked": False,
        "tab_gaps_checked": False,
        "production_safe": False,
        "status": "BLOCKED_DWG_GEOMETRY_DECODER_MISSING",
        "embedded_preview": None,
    }
    offset = data.find(PNG)
    while offset >= 0:
        preview = _validated_png(data, offset)
        if preview is not None:
            payload, (width, height) = preview
            (dest / "embedded_preview_original.png").write_bytes(payload)
            with Image.open(io.BytesIO(payload)) as img:
                rgb = img.convert("RGB")
                rgb.resize((width * 5, height * 5), Image.Resampling.NEAREST).save(
                    dest / "embedded_preview_magnified.png"
                )
            report["embedded_preview"] = {
                "width": width, "height": height, "byte_offset": offset,
                "warning": "Embedded raster thumbnail, NOT vector drawing data"
            }
            break
        offset = data.find(PNG, offset + len(PNG))
    (dest / "preflight_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description="Read-only DWG signature and thumbnail check")
    parser.add_argument("dwg", type=Path)
    parser.add_argument("--out-dir", type=Path, default=Path("preflight_out"))
    args = parser.parse_args()
    print(json.dumps(inspect_dwg(args.dwg, args.out_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
