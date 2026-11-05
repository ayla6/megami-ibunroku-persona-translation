"""Download platform-specific armips and xdelta3 into external_tools/."""
import argparse
import hashlib
import json
import os
import platform
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTERNAL = ROOT / "external_tools"
ARMIPS_RUNS = "https://api.github.com/repos/Kingcom/armips/actions/runs?branch=master&status=success&per_page=20"
XDELTA_VERSION = "3.2.2"
XDELTA_BASE = f"https://github.com/jmacd/xdelta/releases/download/v{XDELTA_VERSION}"
# SHA-256 values published with the v3.2.2 release assets.
XDELTA_ASSETS = {
    ("linux", "arm64"): ("tar.gz", "5efd11af8eb3b74bad056908281b6ffb8a2c0c165955fa643a5a267dfdeb9120"),
    ("linux", "x86_64"): ("tar.gz", "a8ce7d2c943ae2b3d308942643cb36d4805a1f16775abe1be64fee292d7c2506"),
    ("macos", "arm64"): ("tar.gz", "27dcf763beb075ed28061ef136613f4bc6ea3999cb424f23a7d59f18ca2d7c8b"),
    ("macos", "x86_64"): ("tar.gz", "e217f4d0f92357ee890f9d8b5571f7eb836a86ff87e8834bed0b9d9b38630f86"),
    ("windows", "arm64"): ("zip", "877bd98df8aa6665038029e5839fe4d768f029f5eff0f4a1671dac409fc0ce7d"),
    ("windows", "x86"): ("zip", "42429a6719795bb486e91d8928d5bbdba2cead8b2bc8515f812d3cf2f7b3dd55"),
    ("windows", "x86_64"): ("zip", "d48f7651d86b78fdca397057b46601f89131f37219675df736db70af44ec3379"),
}


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


def xdelta_asset(system=None, machine=None):
    system = system or sys.platform
    machine = (machine or platform.machine()).lower()
    os_name = ("linux" if system.startswith("linux") else "macos" if system == "darwin"
               else "windows" if system == "win32" else system)
    arch = {"amd64": "x86_64", "x64": "x86_64", "aarch64": "arm64",
            "i386": "x86", "i686": "x86", "x86_32": "x86"}.get(machine, machine)
    try:
        extension, checksum = XDELTA_ASSETS[(os_name, arch)]
    except KeyError:
        raise RuntimeError(f"no xdelta3 {XDELTA_VERSION} binary for {system}/{machine}; "
                           "install xdelta3 separately or use --skip-xdelta3") from None
    return f"xdelta3-{XDELTA_VERSION}-{os_name}-{arch}.{extension}", checksum


def install_xdelta3(force=False):
    destination = EXTERNAL / "xdelta3"
    name = "xdelta3.exe" if sys.platform == "win32" else "xdelta3"
    executable = destination / name
    if not force and executable.is_file():
        print("xdelta3 already exists; leaving it in place.")
        return
    asset, expected = xdelta_asset()
    archive = fetch(f"{XDELTA_BASE}/{asset}")
    actual = hashlib.sha256(archive).hexdigest()
    if actual != expected:
        raise RuntimeError(f"xdelta3 artifact checksum mismatch: expected {expected}, got {actual}")
    if asset.endswith('.zip'):
        with zipfile.ZipFile(BytesIO(archive)) as zf:
            candidates = [item for item in zf.infolist() if not item.is_dir()
                          and Path(item.filename).name == name]
            if len(candidates) != 1:
                raise RuntimeError(f"{asset}: expected exactly one {name} executable")
            data = zf.read(candidates[0])
    else:
        with tarfile.open(fileobj=BytesIO(archive), mode='r:gz') as tf:
            candidates = [item for item in tf.getmembers() if item.isfile()
                          and Path(item.name).name == name]
            if len(candidates) != 1:
                raise RuntimeError(f"{asset}: expected exactly one {name} executable")
            data = tf.extractfile(candidates[0]).read()
    if not data:
        raise RuntimeError(f"{asset}: empty {name} executable")
    destination.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination, delete=False) as output:
            temp_path = Path(output.name)
            output.write(data)
        if sys.platform != 'win32':
            temp_path.chmod(0o755)
        os.replace(temp_path, executable)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    print(f"Installed {asset} (SHA-256 verified).")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-armips", action="store_true", help="do not download armips")
    parser.add_argument("--skip-xdelta3", action="store_true", help="do not download xdelta3")
    parser.add_argument("--force", action="store_true", help="replace already installed files")
    args = parser.parse_args()

    EXTERNAL.mkdir(parents=True, exist_ok=True)
    if not args.skip_armips:
        install_armips(force=args.force)
    if not args.skip_xdelta3:
        install_xdelta3(force=args.force)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, StopIteration, urllib.error.URLError, zipfile.BadZipFile, tarfile.TarError) as exc:
        raise SystemExit(f"external tool download failed: {exc}")
