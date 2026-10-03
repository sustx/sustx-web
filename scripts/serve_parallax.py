"""Serve the existing site and Parallax API locally without exposing private files."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("parallax", ROOT / "api/parallax.py")
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


class LocalHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def is_api(self):
        return urlsplit(self.path).path == "/api/parallax"

    def do_GET(self):
        if self.is_api():
            api.handler.do_GET(self)
            return
        super().do_GET()

    def do_HEAD(self):
        if self.is_api():
            self.send_error(405)
            return
        super().do_HEAD()

    def do_POST(self):
        if self.is_api():
            api.handler.do_POST(self)
        else:
            self.send_error(404)

    reply = api.handler.reply

    def send_head(self):
        path = Path(unquote(urlsplit(self.path).path).lstrip("/"))
        if (any(part.startswith(".") or part == ".." for part in path.parts)
                or (path.parts and path.parts[0] in {"api", "scripts", "tests", "docs"})
                or (path.name in {"requirements.txt", "vercel.json", "README.md"})
                or (path.suffix == ".parallax-license")):
            self.send_error(404)
            return None
        resolved = (ROOT / path).resolve()
        if not resolved.is_relative_to(ROOT):
            self.send_error(404)
            return None
        return super().send_head()

    def list_directory(self, _path):
        self.send_error(404)
        return None

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if urlsplit(self.path).path.startswith("/parallax/"):
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'; object-src 'none'")
        super().end_headers()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    config = ROOT / ".private/parallax-env.json"
    if config.exists():
        os.environ.update(json.loads(config.read_text()))
    os.environ["PARALLAX_LOCAL"] = "1"
    print(f"Downloads: http://localhost:{args.port}/parallax/", flush=True)
    print(f"Owner page: http://localhost:{args.port}/parallax/admin/", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), partial(LocalHandler, directory=str(ROOT))).serve_forever()
