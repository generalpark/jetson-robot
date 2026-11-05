"""IMX219(CSI) 카메라를 브라우저에서 보는 MJPEG 스트림 서버. Jetson에서 실행.

    python3 cam_stream.py            # http://<jetson>:8090/
    python3 cam_stream.py --width 1920 --height 1080 --fps 15

GStreamer(nvarguscamerasrc -> nvjpegenc)가 JPEG 프레임을 stdout으로 내보내고,
이 스크립트는 SOI/EOI 마커로 프레임을 잘라 최신 한 장만 들고 있다가 접속한 브라우저마다 보낸다.
카메라는 한 번만 열리므로 여러 명이 봐도 부하가 늘지 않는다.
Jetson ufw는 tailscale0만 열려 있어서 집 밖에서도 Tailscale로만 볼 수 있다.
"""
import argparse
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ap = argparse.ArgumentParser()
ap.add_argument("--sensor", type=int, default=0)
ap.add_argument("--width", type=int, default=1280)
ap.add_argument("--height", type=int, default=720)
ap.add_argument("--fps", type=int, default=30)
ap.add_argument("--port", type=int, default=8090)
args = ap.parse_args()

PIPE = (
    f"gst-launch-1.0 -q nvarguscamerasrc sensor-id={args.sensor} ! "
    f"'video/x-raw(memory:NVMM),width={args.width},height={args.height},framerate={args.fps}/1' ! "
    "nvjpegenc quality=80 ! fdsink fd=1"
)

latest = None          # 가장 최근 JPEG 한 장
seq = 0                # 프레임 번호 — 클라이언트가 같은 프레임을 두 번 보내지 않게
cond = threading.Condition()
stats = {"frames": 0, "t0": time.time()}


def capture():
    global latest, seq
    proc = subprocess.Popen(PIPE, shell=True, stdout=subprocess.PIPE, bufsize=0)
    buf = b""
    while True:
        chunk = proc.stdout.read(65536)
        if not chunk:
            raise SystemExit("[cam] gstreamer 종료 — 카메라 연결·다른 프로세스 점유 확인")
        buf += chunk
        while True:
            s = buf.find(b"\xff\xd8")
            e = buf.find(b"\xff\xd9", s + 2)
            if s < 0 or e < 0:
                break
            frame, buf = buf[s:e + 2], buf[e + 2:]
            with cond:
                latest, seq = frame, seq + 1
                stats["frames"] += 1
                cond.notify_all()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/":
            body = (
                "<html><body style='margin:0;background:#111'>"
                "<img src='/stream' style='width:100%;height:auto'></body></html>"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/snapshot.jpg":
            with cond:
                cond.wait_for(lambda: latest is not None, timeout=5)
                frame = latest
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.end_headers()
            self.wfile.write(frame)
        elif self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            last = -1
            try:
                while True:
                    with cond:
                        cond.wait_for(lambda: seq != last, timeout=5)
                        frame, last = latest, seq
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode())
                    self.wfile.write(frame + b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass
        elif self.path == "/health":
            fps = stats["frames"] / max(time.time() - stats["t0"], 1e-6)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"frames={stats['frames']} avg_fps={fps:.1f}\n".encode())
        else:
            self.send_error(404)


threading.Thread(target=capture, daemon=True).start()
print(f"[cam] http://0.0.0.0:{args.port}/  ({args.width}x{args.height}@{args.fps})")
ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()
