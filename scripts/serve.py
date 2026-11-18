"""Loopback-only QA server. Public web files plus explicitly generated test audio."""
import argparse
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote,urlsplit
ROOT=Path(__file__).resolve().parents[1]
class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204);self.send_header('Access-Control-Allow-Origin','*');self.send_header('Access-Control-Allow-Headers','Range');self.end_headers()
    def do_HEAD(self):self.send_file(True)
    def do_GET(self):self.send_file(False)
    def send_file(self,head):
        request=unquote(urlsplit(self.path).path)
        root=ALBUM if request.startswith('/local/') else ROOT/'web'
        relative=request[len('/local/'):] if request.startswith('/local/') else request.lstrip('/')
        target=(root/(relative or 'index.html')).resolve()
        if not target.is_relative_to(root.resolve()) or not target.is_file():self.send_error(404);return
        size=target.stat().st_size;start,end=0,size-1;status=200
        if self.headers.get('Range'):
            m=re.fullmatch(r'bytes=(\d*)-(\d*)',self.headers['Range'])
            if not m or not any(m.groups()):self.send_error(416);return
            start=int(m[1]) if m[1] else max(0,size-int(m[2]));end=min(size-1,int(m[2])) if m[1] and m[2] else size-1
            if start>end or start>=size:self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.end_headers();return
            status=206
        self.send_response(status);self.send_header('Content-Type',mimetypes.guess_type(target)[0] or 'application/octet-stream');self.send_header('Content-Length',str(end-start+1));self.send_header('Accept-Ranges','bytes');self.send_header('Access-Control-Allow-Origin','*');self.send_header('Cache-Control','no-store')
        if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.end_headers()
        if not head:
            try:
                with target.open('rb') as f:
                    f.seek(start);remaining=end-start+1
                    while remaining:
                        data=f.read(min(1024*1024,remaining));self.wfile.write(data);remaining-=len(data)
            except (BrokenPipeError,ConnectionResetError):pass
    def log_message(self,*args):pass
p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8765);p.add_argument('--album',default='output/validation');args=p.parse_args();ALBUM=(ROOT/args.album).resolve();print(f'Local preview: http://127.0.0.1:{args.port}',flush=True);ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
