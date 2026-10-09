"""Loopback Turborepo Remote Cache API adapter backed by nanocompile's Zig CAS.

One configured team/token. Run behind an authenticated TLS proxy for remote use;
this development server binds only to loopback. Archives stay opaque here.
"""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import socketserver
import subprocess
import tempfile
from urllib.parse import parse_qs, urlsplit

HASH = re.compile(r'[a-fA-F0-9]{1,128}\Z')


class Server(ThreadingHTTPServer):
    def server_bind(self):
        # The standard HTTPServer resolves a reverse DNS name during bind.
        # A loopback cache must start even when the host's resolver is offline.
        socketserver.TCPServer.server_bind(self)
        self.server_name = 'localhost'
        self.server_port = self.server_address[1]


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass  # Request paths, headers and bearer tokens are not logged.

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def reply(self, code, data=None, headers=None):
        body = b'' if data is None else json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, str(v))
        if code >= 400:
            self.close_connection = True
            self.send_header('Connection', 'close')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def authorize(self):
        expected = ('Bearer ' + self.server.token).encode()
        if not hmac.compare_digest(self.headers.get('Authorization', '').encode(), expected):
            self.reply(401, {'error': 'unauthorized'})
            return None
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        for name in ('teamId', 'slug'):
            if name in query and query[name] != [self.server.team]:
                self.reply(403, {'error': 'team mismatch'})
                return None
        return re.sub(r'^/v8(?=/)', '', url.path)

    def body(self, limit):
        if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
            raise ValueError('length required')
        n = int(self.headers['Content-Length'])
        if n < 0 or n > limit:
            raise ValueError('size limit')
        return n

    def invoke(self, op, key, *args):
        p = subprocess.run([self.server.binary, 'artifact', op, 'turbo/' + self.server.team,
                            key.lower(), *map(str, args)], env=self.server.env,
                           capture_output=True, timeout=120)
        if p.returncode == 3:
            return None
        if p.returncode:
            raise RuntimeError('artifact backend failed')
        return json.loads(p.stdout)

    def artifact(self, path):
        if not path.startswith('/artifacts/') or not HASH.fullmatch(path[len('/artifacts/'):]):
            return None
        return path[len('/artifacts/'):]

    def metadata(self):
        duration = int(self.headers.get('x-artifact-duration', '0'))
        if duration < 0 or duration > 2**63 - 1:
            raise ValueError('invalid duration')
        result = {'duration': duration}
        for name, limit in [('tag', 600), ('sha', 128), ('dirty-hash', 128)]:
            value = self.headers.get('x-artifact-' + name)
            if value is not None:
                if len(value) > limit or any(ord(ch) < 32 or ord(ch) > 126 for ch in value):
                    raise ValueError('invalid metadata')
                result[name] = value
        return result

    def do_PUT(self):
        path = self.authorize()
        if path is None:
            return
        key = self.artifact(path)
        if key is None:
            return self.reply(404)
        try:
            remaining = self.body(self.server.max_bytes)
            metadata = self.metadata()
            with tempfile.TemporaryDirectory(prefix='turbo-upload-') as temp:
                archive = Path(temp) / 'artifact'
                with archive.open('wb') as f:
                    while remaining:
                        chunk = self.rfile.read(min(remaining, 64 * 1024))
                        if not chunk:
                            raise ValueError('truncated body')
                        f.write(chunk)
                        remaining -= len(chunk)
                self.invoke('put', key, archive, json.dumps(metadata))
            self.reply(200, {'urls': []})
        except (ValueError, TimeoutError):
            self.reply(400, {'error': 'invalid upload'})
        except Exception:
            self.reply(500, {'error': 'cache unavailable'})

    def do_GET(self):
        path = self.authorize()
        if path is None:
            return
        if path == '/artifacts/status':
            return self.reply(200, {'status': 'enabled'})
        key = self.artifact(path)
        if key is None:
            return self.reply(404)
        responded = False
        try:
            with tempfile.TemporaryDirectory(prefix='turbo-download-') as temp:
                archive = Path(temp) / 'artifact'
                record = self.invoke('head' if self.command == 'HEAD' else 'get', key,
                                     *([] if self.command == 'HEAD' else [archive]))
                if record is None:
                    return self.reply(404)
                metadata = json.loads(record['metadata'])
                self.send_response(200)
                responded = True
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Length', str(record['bytes']))
                for k, v in metadata.items():
                    self.send_header('x-artifact-' + k, str(v))
                self.end_headers()
                if self.command != 'HEAD':
                    with archive.open('rb') as f:
                        shutil.copyfileobj(f, self.wfile, 64 * 1024)
        except Exception:
            self.close_connection = True
            if not responded:
                self.reply(500, {'error': 'cache unavailable'})

    do_HEAD = do_GET

    def do_POST(self):
        path = self.authorize()
        if path is None:
            return
        if path not in ('/artifacts', '/artifacts/events'):
            return self.reply(404)
        try:
            n = self.body(256 * 1024)
            data = json.loads(self.rfile.read(n))
            if path == '/artifacts/events':
                if not isinstance(data, list):
                    raise ValueError('invalid events')
                return self.reply(200)
            hashes = data['hashes']
            if not isinstance(hashes, list) or len(hashes) > 1000 or any(not isinstance(h, str) or not HASH.fullmatch(h) for h in hashes):
                raise ValueError('invalid hashes')
            result = {}
            for h in hashes:
                record = self.invoke('head', h)
                result[h] = None if record is None else {'size': record['bytes'], 'taskDurationMs': json.loads(record['metadata']).get('duration', 0)}
            self.reply(200, result)
        except (ValueError, KeyError, TypeError):
            self.reply(400, {'error': 'invalid request'})
        except Exception:
            self.reply(500, {'error': 'cache unavailable'})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--nanocompile', required=True)
    p.add_argument('--cache', required=True)
    p.add_argument('--team', default='nanocompile-example')
    p.add_argument('--port', type=int, default=9080)
    p.add_argument('--max-bytes', type=int, default=256 * 1024 * 1024)
    args = p.parse_args()
    token = os.environ.get('NANOCOMPILE_TURBO_TOKEN')
    if not token or not token.isascii() or len(token) < 16 or '\r' in token or '\n' in token:
        p.error('set NANOCOMPILE_TURBO_TOKEN to an ASCII token of at least 16 characters')
    if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,128}', args.team) or args.max_bytes < 1:
        p.error('invalid team or size limit')
    server = Server(('127.0.0.1', args.port), Handler)
    server.token, server.team = token, args.team
    server.binary = str(Path(args.nanocompile).resolve())
    server.env = dict(os.environ, NANOCOMPILE_DIR=str(Path(args.cache).resolve()))
    server.max_bytes = args.max_bytes
    print(json.dumps({'ready': True, 'port': server.server_port, 'team': args.team}), flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
