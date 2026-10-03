"""Prepare owner credentials locally, or upload them to a linked Vercel project."""
import argparse
import base64
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".private/parallax-env.json"


def private_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(text)


def prepare(key_path):
    if CONFIG.exists() or (ROOT / ".private/parallax-owner.txt").exists():
        raise ValueError("Owner access already exists. Refusing to replace credentials.")
    pem = key_path.read_bytes()
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Expected the existing Ed25519 private key")
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    expected = json.loads((ROOT / "parallax/release.json").read_text())["public_key"]
    if public != expected:
        raise ValueError("The key does not match the published release. Do not generate a new key.")
    spec = importlib.util.spec_from_file_location("parallax", ROOT / "api/parallax.py")
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    password = secrets.token_urlsafe(24)
    values = {"PARALLAX_ADMIN_PASSWORD_HASH": api.password_hash(password),
              "PARALLAX_SESSION_SECRET": secrets.token_urlsafe(48),
              "PARALLAX_SIGNING_KEY_BASE64": base64.b64encode(pem).decode()}
    private_write(CONFIG, json.dumps(values, indent=2) + "\n")
    private_write(ROOT / ".private/parallax-owner.txt",
                  "Parallax owner access\n\nPage: /parallax/admin/\nOwner password: " + password +
                  "\n\nStore this password in your password manager. Do not send it to customers.\n")
    print("Owner access prepared. Password: .private/parallax-owner.txt (not printed).")
    print("Server settings: .private/parallax-env.json (excluded from Git and deployment).")


def upload(environment):
    cli = shutil.which("vercel")
    if not cli or not (ROOT / ".vercel/project.json").is_file():
        raise ValueError("Install/sign in to Vercel CLI and run vercel link to the existing sustx-web project first.")
    values = json.loads(CONFIG.read_text())
    for name, value in values.items():
        # Values travel over stdin, never argv, logs, or shell interpolation.
        result = subprocess.run([cli, "env", "add", name, environment, "--sensitive"],
                                input=value + "\n", text=True, capture_output=True, cwd=ROOT)
        if result.returncode:
            raise ValueError(f"Could not add {name}. Check login/project permissions and whether it already exists.")
        print(f"Added {name} to {environment}.")
    print("Server settings uploaded. Deploy separately when ready.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-key", type=Path)
    parser.add_argument("--upload", choices=("production", "preview"))
    args = parser.parse_args()
    try:
        if args.upload:
            upload(args.upload)
        elif args.private_key:
            prepare(args.private_key)
        else:
            parser.error("Choose --private-key PATH or --upload production|preview")
    except (ValueError, OSError) as error:
        parser.exit(1, f"Error: {error}\n")
