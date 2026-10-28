"""Serve the team demo locally, bound to this computer only."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, default=8080)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1] / 'site'
print(f'Open http://127.0.0.1:{args.port}/ ; Ctrl+C to stop.', flush=True)
with ThreadingHTTPServer(('127.0.0.1', args.port), partial(SimpleHTTPRequestHandler, directory=str(root))) as server:
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
