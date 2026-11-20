"""Download platform-specific armips into external_tools/."""
import argparse
import hashlib
import json
import os
import platform
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTERNAL = ROOT / "external_tools"
ARMIPS_RUNS = "https://api.github.com/repos/Kingcom/armips/actions/runs?branch=master&status=success&per_page=20"
def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Persona-PSX-translation-setup"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def github_json(url):
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "Persona-PSX-translation-setup",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def armips_suffix():
    if sys.platform.startswith("linux"):
        return "_ubuntu_gcc"
    if sys.platform == "darwin":
        return "_macos_clang"
    if sys.platform == "win32":
        return "_windows_msvc"
    raise RuntimeError(f"no armips workflow artifact configured for {sys.platform}")


def armips_artifact():
    runs = github_json(ARMIPS_RUNS)["workflow_runs"]
    run = next(r for r in runs if r["path"] == ".github/workflows/build.yml"
               and r["event"] == "push" and r["conclusion"] == "success")
    artifacts = github_json(run["artifacts_url"])["artifacts"]
    suffix = armips_suffix()
    artifact = next(a for a in artifacts if not a["expired"] and a["name"].endswith(suffix))
    return run, artifact


def install_armips(force=False):
    destination = EXTERNAL / "armips"
    executable_names = {"armips", "armips.exe"}
    if not force and any((destination / name).is_file() for name in executable_names):
        print("armips already exists; leaving it in place.")
        return

    run, artifact = armips_artifact()
    # GitHub requires authentication for Actions artifacts. nightly.link relays
    # public-repository artifacts anonymously and redirects to GitHub's zip.
    url = (f"https://nightly.link/Kingcom/armips/suites/{run['check_suite_id']}"
           f"/artifacts/{artifact['id']}")
    archive = fetch(url)
    expected = (artifact.get("digest") or "").removeprefix("sha256:")
    actual = hashlib.sha256(archive).hexdigest()
    if expected and actual != expected:
        raise RuntimeError(f"armips artifact checksum mismatch: expected {expected}, got {actual}")

    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(BytesIO(archive)) as zf:
        files = [item for item in zf.infolist() if not item.is_dir()]
        executable = next((item for item in files if Path(item.filename).name in executable_names), None)
        if executable is None:
            raise RuntimeError(f"artifact {artifact['name']} does not contain an armips executable")
        for item in files:
            (destination / Path(item.filename).name).write_bytes(zf.read(item))
    if sys.platform != "win32":
        (destination / "armips").chmod(0o755)
    print(f"Installed {artifact['name']} from successful armips Actions run {run['run_number']}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-armips", action="store_true", help="do not download armips")
    parser.add_argument("--force", action="store_true", help="replace already installed files")
    args = parser.parse_args()

    EXTERNAL.mkdir(parents=True, exist_ok=True)
    if not args.skip_armips:
        install_armips(force=args.force)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, StopIteration, urllib.error.URLError, zipfile.BadZipFile) as exc:
        raise SystemExit(f"external tool download failed: {exc}")
