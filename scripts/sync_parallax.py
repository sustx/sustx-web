"""Copy a versioned Parallax release and public key, never its private key."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile

SITE = Path(__file__).resolve().parents[1]


def sync(project):
    project = project.resolve()
    version = (project / "VERSION.txt").read_text().strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Invalid VERSION.txt")
    source = project / "dist" / f"parallax-{version}"
    if not source.is_dir():
        source = project / "dist"
    names = {"mac": f"Parallax-{version}-macOS.pkg",
             "windows": f"Parallax-{version}-Windows-x64-Setup.exe",
             "windows_zip": f"Parallax-{version}-Windows-x64-VST3.zip"}
    files = {key: source / name for key, name in names.items()}
    for path in files.values():
        if not path.is_file():
            raise ValueError(f"Missing release artifact: {path}")
    exe = files["windows"].read_bytes()
    if exe[:2] != b"MZ":
        raise ValueError("Windows installer must be a PE executable")
    with zipfile.ZipFile(files["windows_zip"]) as archive:
        if archive.testzip():
            raise ValueError("Windows VST3 ZIP is corrupt")
        binary = archive.read("Parallax.vst3/Contents/x86_64-win/Parallax.vst3")
        offset = int.from_bytes(binary[0x3c:0x40], "little")
        if binary[:2] != b"MZ" or binary[offset:offset + 6] != b"PE\0\0\x64\x86":
            raise ValueError("ZIP must contain the Windows x64 VST3")
    header = (project / "Source/LicensingPublicKey.h").read_text()
    key = bytes(int(value, 16) for value in re.findall(r"0x([0-9a-fA-F]{2})", header))
    if len(key) != 32:
        raise ValueError("Expected the release's 32-byte Ed25519 public key")
    destination = SITE / "downloads/parallax" / version
    destination.mkdir(parents=True, exist_ok=True)
    release = {"version": version, "public_key": key.hex(), "files": {}}
    for identifier, path in files.items():
        output = destination / path.name
        if output.exists() and output.read_bytes() != path.read_bytes():
            raise ValueError(f"Refusing to replace a different published artifact: {output}. Use a new version.")
        shutil.copyfile(path, output)
        release["files"][identifier] = {"filename": path.name,
            "url": f"/downloads/parallax/{version}/{path.name}",
            "bytes": output.stat().st_size,
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}
    (SITE / "parallax").mkdir(exist_ok=True)
    (SITE / "parallax/release.json").write_text(json.dumps(release, indent=2) + "\n")
    print(f"Synced Parallax v{version}: Mac installer, Windows installer, Windows VST3 ZIP, and public key.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plugin_project", type=Path)
    sync(parser.parse_args().plugin_project)
