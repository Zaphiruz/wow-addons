"""Release helper for the addons in mods/classic. Standard library only.

  python release.py check  <Addon> <version>   tag version must match the .toc, changelog must cover it
  python release.py notes  <Addon>             print this version's changelog section
  python release.py upload <Addon> [--dry-run] upload dist/<Addon>-<version>.zip to CurseForge

Tags look like "Hawker/v0.1.0":    python release.py tag Hawker/v0.1.0  prints "Hawker 0.1.0".

Upload reads the CurseForge project from "## X-Curse-Project-ID:" in the .toc,
the game versions from "## Interface:" (11509 -> 1.15.9), and the API token
from the CF_API_TOKEN environment variable.
"""
import argparse
import json
import os
import pathlib
import re
import sys
import urllib.request
import uuid
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parent.parent
API = "https://wow.curseforge.com/api"
USER_AGENT = "wow-addons-release/1.0"


class ReleaseError(Exception):
    pass


@dataclass
class Release:
    addon: str
    version: str
    game_versions: list
    project_id: str
    changelog: str
    zip_path: pathlib.Path


def read_toc(path):
    meta = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^##\s*([^:]+):\s*(.*?)\s*$", line)
        if m:
            meta[m.group(1)] = m.group(2)
    return meta


def interface_to_version(interface):
    """11509 -> 1.15.9, 120105 -> 12.1.5"""
    interface = str(interface).strip()
    if not interface.isdigit() or len(interface) < 5:
        raise ReleaseError(f"can't read Interface number {interface!r}")
    n = int(interface)
    return f"{n // 10000}.{(n // 100) % 100}.{n % 100}"


def parse_tag(tag):
    m = re.fullmatch(r"([A-Za-z][\w-]*)/v(\d[\w.\-]*)", tag)
    if not m:
        raise ReleaseError(f"tag {tag!r} should look like Addon/v1.2.3")
    return m.group(1), m.group(2)


def changelog_section(text, version):
    """Body of the '## <version>' section, without its heading, or None."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.match(rf"^##\s+{re.escape(version)}(\s|$)", line):
            body = []
            for nxt in lines[i + 1:]:
                if nxt.startswith("## "):
                    break
                body.append(nxt)
            return "\n".join(body).strip()
    return None


def release_type(version):
    v = version.lower()
    if "alpha" in v:
        return "alpha"
    if "beta" in v:
        return "beta"
    return "release"


def resolve_game_version(versions, name):
    matches = [v["id"] for v in versions if v.get("name") == name]
    if len(matches) != 1:
        raise ReleaseError(f"CurseForge has {len(matches)} game versions named {name!r}, expected exactly 1")
    return matches[0]


def multipart(fields, file_field, filename, data):
    boundary = uuid.uuid4().hex
    out = bytearray()
    for name, value in fields.items():
        out += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n".encode()
        out += value.encode() + b"\r\n"
    out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; filename=\"{filename}\"\r\n"
            "Content-Type: application/zip\r\n\r\n").encode()
    out += data + f"\r\n--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def load(addon, root=ROOT):
    folder = root / addon
    toc_path = folder / f"{addon}.toc"
    if not toc_path.is_file():
        raise ReleaseError(f"no {toc_path}")
    toc = read_toc(toc_path)
    version = toc.get("Version")
    if not version:
        raise ReleaseError(f"{toc_path.name} has no '## Version:' line")
    interfaces = [i for i in toc.get("Interface", "").replace(" ", "").split(",") if i]
    if not interfaces:
        raise ReleaseError(f"{toc_path.name} has no '## Interface:' line")
    changelog_path = folder / "CHANGELOG.md"
    text = changelog_path.read_text(encoding="utf-8") if changelog_path.is_file() else ""
    return Release(
        addon=addon,
        version=version,
        game_versions=[interface_to_version(i) for i in interfaces],
        project_id=toc.get("X-Curse-Project-ID", ""),
        changelog=changelog_section(text, version),
        zip_path=root / "dist" / f"{addon}-{version}.zip",
    )


def check(addon, tag_version, root=ROOT):
    tag_version = tag_version.strip()
    r = load(addon, root)
    if r.version != tag_version:
        raise ReleaseError(f"tag says {tag_version} but {addon}.toc says {r.version}")
    if not r.changelog:
        raise ReleaseError(f"{addon}/CHANGELOG.md has no '## {r.version}' section")
    return r


def api(path, token, opener, data=None, content_type=None):
    req = urllib.request.Request(f"{API}{path}", data=data, method="POST" if data else "GET")
    req.add_header("X-Api-Token", token)
    req.add_header("User-Agent", USER_AGENT)
    if content_type:
        req.add_header("Content-Type", content_type)
    with opener(req, timeout=120) as resp:
        return json.loads(resp.read())


def upload(addon, token, root=ROOT, opener=urllib.request.urlopen, dry_run=False):
    r = load(addon, root)
    if not r.changelog:
        raise ReleaseError(f"{addon}/CHANGELOG.md has no '## {r.version}' section")
    meta = {
        "changelog": r.changelog,
        "changelogType": "markdown",
        "displayName": f"{addon} {r.version}",
        "releaseType": release_type(r.version),
    }
    if dry_run:
        meta["gameVersionNames"] = r.game_versions
        return meta
    if not r.project_id:
        raise ReleaseError(f"add '## X-Curse-Project-ID: <id>' to {addon}.toc (the id is on the CurseForge project page)")
    if not token:
        raise ReleaseError("set the CF_API_TOKEN environment variable to a CurseForge API token")
    if not r.zip_path.is_file():
        raise ReleaseError(f"{r.zip_path} not found; build it with tools/package.py {addon}")
    known = api("/game/versions", token, opener)
    meta["gameVersions"] = [resolve_game_version(known, v) for v in r.game_versions]
    body, ctype = multipart({"metadata": json.dumps(meta)}, "file", r.zip_path.name, r.zip_path.read_bytes())
    result = api(f"/projects/{r.project_id}/upload-file", token, opener, data=body, content_type=ctype)
    return result["id"]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tag").add_argument("tag")
    c = sub.add_parser("check")
    c.add_argument("addon")
    c.add_argument("version")
    sub.add_parser("notes").add_argument("addon")
    u = sub.add_parser("upload")
    u.add_argument("addon")
    u.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    try:
        if args.cmd == "tag":
            print(*parse_tag(args.tag))
        elif args.cmd == "check":
            r = check(args.addon, args.version)
            print(f"{r.addon} {r.version} for game {', '.join(r.game_versions)}: ok")
        elif args.cmd == "notes":
            r = load(args.addon)
            if not r.changelog:
                raise ReleaseError(f"{args.addon}/CHANGELOG.md has no '## {r.version}' section")
            print(r.changelog)
        elif args.cmd == "upload":
            result = upload(args.addon, os.environ.get("CF_API_TOKEN", ""), dry_run=args.dry_run)
            if args.dry_run:
                print(json.dumps(result, indent=2))
            else:
                print(f"uploaded {args.addon} to CurseForge as file {result}")
    except ReleaseError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
