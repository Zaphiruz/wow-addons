"""Runs the mock-game tests for each addon, plus the release tool's tests.

Usage: python run_tests.py            every addon and the tools
       python run_tests.py Hawker     just one addon
Needs the lupa package (pip install lupa) for the addon tests.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def addons():
    return sorted(p.name for p in ROOT.iterdir() if (p / f"{p.name}.toc").is_file())


def main(names):
    failed = []
    for addon in names or addons():
        runner = ROOT / "tests" / addon.lower() / "run_tests.py"
        if not runner.is_file():
            print(f"== {addon}: no tests found at {runner.relative_to(ROOT)}")
            failed.append(addon)
            continue
        print(f"== {addon}", flush=True)
        if subprocess.run([sys.executable, str(runner), str(ROOT / addon / f"{addon}.lua")]).returncode:
            failed.append(addon)
    if not names:
        print("== release tools", flush=True)
        cmd = [sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests" / "tools")]
        if subprocess.run(cmd).returncode:
            failed.append("release tools")
    print("failed: " + (", ".join(failed) if failed else "none"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
