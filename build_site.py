"""Create a public-only static output, keeping server code and secrets out."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "public"
FILES = ("index.html", "song.html", "style.6e85a912.css", "data.aa714b12.js")
DIRECTORIES = ("assets", "fonts", "parallax", "downloads")


def ignored(_directory, names):
    return [name for name in names if name.startswith(".") or name == "__pycache__"
            or name.endswith((".py", ".pem", ".parallax-license"))]


def build():
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir()
    for name in FILES:
        shutil.copyfile(ROOT / name, OUTPUT / name)
    for name in DIRECTORIES:
        shutil.copytree(ROOT / name, OUTPUT / name, ignore=ignored)
    print("Built public pages, assets and downloads; server code and private storage excluded.")


if __name__ == "__main__":
    build()
