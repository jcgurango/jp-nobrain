#!/usr/bin/env python3
"""Local web app: python3 -I app/server.py [port]   (default 8765). No dependencies beyond the stdlib."""
import json, mimetypes, os, re, sys, threading, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, scheduler

ROOT = db.ROOT
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
MEDIA = os.path.join(ROOT, 'media')
LOCK = threading.Lock()
CON = db.connect()

class Handler(BaseHTTPRequestHandler):
    server_version = 'jp-nobrain/0.1'

    def log_message(self, fmt, *args):
        if args and '/api/' in str(args[0]): return
        sys.stderr.write('%s %s\n' % (self.address_string(), fmt % args))

    # ---- helpers
    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers(); self.wfile.write(body)

    def read_json(self):
        n = int(self.headers.get('Content-Length') or 0)
        return json.loads(self.rfile.read(n) or b'{}')

    def send_file(self, path, cache=False):
        if not os.path.isfile(path):
            self.send_error(404); return
        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(path)[0] or 'application/octet-stream'
        if path.endswith('.webp'): ctype = 'image/webp'
        start, end = 0, size - 1
        rng = self.headers.get('Range')
        status = 200
        if rng:
            m = re.match(r'bytes=(\d*)-(\d*)', rng)
            if m:
                if m.group(1): start = int(m.group(1))
                if m.group(2): end = min(int(m.group(2)), size - 1)
                if not m.group(1) and m.group(2): start = max(0, size - int(m.group(2))); end = size - 1
                status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(length))
        if status == 206: self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.send_header('Cache-Control', 'public, max-age=86400' if cache else 'no-cache')
        self.end_headers()
        with open(path, 'rb') as f:
            f.seek(start); remaining = length
            while remaining > 0:
                chunk = f.read(min(65536, remaining))
                if not chunk: break
                try: self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError): return
                remaining -= len(chunk)

    def safe_join(self, base, rel):
        p = os.path.normpath(os.path.join(base, urllib.parse.unquote(rel)))
        return p if p.startswith(base + os.sep) or p == base else None

    # ---- routing
    def do_GET(self):
        u = urllib.parse.urlparse(self.path); q = urllib.parse.parse_qs(u.query)
        g = lambda k, d=None: q.get(k, [d])[0]
        try:
            if u.path == '/' or u.path == '/index.html':
                return self.send_file(os.path.join(STATIC, 'index.html'))
            if u.path.startswith('/static/'):
                p = self.safe_join(STATIC, u.path[len('/static/'):]); return self.send_file(p) if p else self.send_error(404)
            if u.path.startswith('/media/'):
                p = self.safe_join(MEDIA, u.path[len('/media/'):]); return self.send_file(p, cache=True) if p else self.send_error(404)
            with LOCK:
                if u.path == '/api/overview': return self.send_json(scheduler.overview(CON))
                if u.path == '/api/next': return self.send_json(scheduler.next_item(CON, g('tier', 'all'), g('ignore_cap') == '1', g('exclude')))
                if u.path == '/api/shadow': return self.send_json(scheduler.shadow(CON, int(g('limit', 400))))
                if u.path == '/api/browse': return self.send_json(scheduler.browse(CON, int(g('offset', 0)), int(g('limit', 50)), g('filter', 'all')))
                if u.path == '/api/stats': return self.send_json(scheduler.stats(CON))
                if u.path == '/api/settings': return self.send_json(db.get_settings(CON))
                if u.path.startswith('/api/card/'):
                    r = CON.execute('SELECT * FROM cards WHERE id=?', (urllib.parse.unquote(u.path[10:]),)).fetchone()
                    if not r: return self.send_json({'error': 'not found'}, 404)
                    d = db.card_row_to_dict(r)
                    d['tiers'] = {t['tier']: dict(t) for t in CON.execute('SELECT * FROM tier_state WHERE card_id=?', (d['id'],))}
                    m = CON.execute('SELECT * FROM card_meta WHERE card_id=?', (d['id'],)).fetchone(); d['meta'] = dict(m) if m else None
                    return self.send_json(d)
            self.send_error(404)
        except Exception as e:
            import traceback; traceback.print_exc()
            self.send_json({'error': str(e)}, 500)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        try:
            body = self.read_json()
            with LOCK:
                if u.path == '/api/review':
                    return self.send_json(scheduler.review(CON, body['card_id'], body['tier'], body['grade']))
                if u.path == '/api/undo':
                    return self.send_json({'undone': scheduler.undo_last(CON)})
                if u.path == '/api/settings':
                    db.set_settings(CON, body); return self.send_json(db.get_settings(CON))
            self.send_error(404)
        except ValueError as e:
            self.send_json({'error': str(e)}, 400)
        except Exception as e:
            import traceback; traceback.print_exc()
            self.send_json({'error': str(e)}, 500)

def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get('JP_PORT', 8765))
    host = os.environ.get('JP_HOST', '127.0.0.1')
    if CON.execute('SELECT count(*) FROM cards').fetchone()[0] == 0:
        print('No cards in the database yet. Run: python3 -I app/import_deck.py'); sys.exit(1)
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f'jp-nobrain running at http://{host}:{port}/  (db: {db.DB_PATH})')
    try: srv.serve_forever()
    except KeyboardInterrupt: pass

if __name__ == '__main__':
    main()
