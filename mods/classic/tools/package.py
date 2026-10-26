"""Builds a CurseForge upload zip for one addon.

Usage: python package.py <AddonFolder>     e.g. python package.py Hawker
Run from anywhere; paths are relative to mods/classic.

The zip holds one top-level folder named after the addon, containing the
.toc and every file the .toc loads. The version comes from "## Version:".
Output: mods/classic/dist/<Addon>-<version>.zip
"""
import pathlib
import re
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main(name):
    src = ROOT / name
    toc = src / f"{name}.toc"
    text = toc.read_text(encoding="utf-8")
    version = re.search(r"^## Version:\s*(\S+)", text, re.M)
    if not version:
        sys.exit(f"{toc} has no '## Version:' line")
    files = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
    missing = [f for f in files if not (src / f).is_file()]
    if missing:
        sys.exit(f"files listed in {toc.name} are missing: {missing}")

    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    out = dist / f"{name}-{version.group(1)}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(toc, f"{name}/{toc.name}")
        for f in files:
            z.write(src / f, f"{name}/{f}")
    with zipfile.ZipFile(out) as z:
        bad = z.testzip()
        if bad:
            sys.exit(f"corrupt entry {bad} in {out}")
        print(out)
        for info in z.infolist():
            print(f"  {info.filename}  {info.file_size} bytes")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
