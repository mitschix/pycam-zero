#!/usr/bin/python3

# This is the same as mjpeg_server_2.py, but allows 90 or 270 degree rotations.

import io
import logging
import socketserver
from datetime import datetime, timedelta
from http import server
from threading import Condition

import piexif
from libcamera import Transform
from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder, Quality
from picamera2.outputs import FileOutput

ROTATION = 0  # Use 0, 90 or 270
# WIDTH = 1944
# HEIGHT = 2592

rotation_header = bytes()
if ROTATION:
    #    WIDTH, HEIGHT = HEIGHT, WIDTH
    code = 6 if ROTATION == 90 else 8
    exif_bytes = piexif.dump({"0th": {piexif.ImageIFD.Orientation: code}})
    exif_len = len(exif_bytes) + 2
    rotation_header = bytes.fromhex("ffe1") + exif_len.to_bytes(2, "big") + exif_bytes

PAGE = """
<html>
<head>
<title>PyCam <3</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
    body {
        background-color: #333;
        height: 100vh;
        margin: 0;
        display: flex;
        justify-content: center;
        align-items: center;
    }

    img {
        max-width: 100%;
        height: auto;
    }
</style>
</head>
<body >
<img src="stream" />
</body>
</html>
"""
# <img src="stream.mjpg" width="{WIDTH}" height="{HEIGHT}" />


def active_stream_cam(func):
    """Decorator that handles active stream cams."""

    def wrap(self, *args, **kwargs):
        if not self.active_stream:
            start_cam()
        result = func(self, *args, **kwargs)

        if not self.active_stream or datetime.now() > self.last_stream_time:
            stop_cam()
            self.active_stream = False

        return result

    return wrap


class StreamingHandler(server.BaseHTTPRequestHandler):
    active_stream = False
    last_stream_time = datetime.now()
    streaming_time = 1

    @active_stream_cam
    def create_still(self):
        request = picam2.capture_request()
        request.save("main", "/home/pi/still.jpg")
        request.release()
        print("Still image captured!")
        with open("/home/pi/still.jpg", "rb") as file:
            self.wfile.write(file.read())

    @active_stream_cam
    def stream(self):
        self.active_stream = True
        start_time = datetime.now()
        current_end = start_time + timedelta(minutes=self.streaming_time)
        self.last_stream_time = current_end
        logging.info("Stream stop changed to %s", current_end)
        try:
            while datetime.now() < current_end:
                with output.condition:
                    output.condition.wait()
                    frame = output.frame
                self.wfile.write(b"--FRAME\r\n")
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", len(frame))
                self.end_headers()
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
        except Exception as e:
            logging.warning(
                "Removed streaming client %s: %s", self.client_address, str(e)
            )

    def do_GET(self):
        if self.path == "/":
            # self.send_response(301)
            # self.send_header('Location', '/index')
            # self.end_headers()
            content = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", len(content))
            self.end_headers()
            self.wfile.write(content)
        elif self.path == "/index":
            content = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", len(content))
            self.end_headers()
            self.wfile.write(content)
        elif self.path == "/cap":
            self.send_response(200)
            self.end_headers()
            self.create_still()
        elif self.path == "/stream":
            self.send_response(200)
            self.send_header("Age", 0)
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header(
                "Content-Type", "multipart/x-mixed-replace; boundary=FRAME"
            )
            self.end_headers()
            self.stream()
        else:
            self.send_error(404)
            self.end_headers()


class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf[:2] + rotation_header + buf[2:]
            self.condition.notify_all()


class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def start_cam():
    logging.info("Cam started - %s!", datetime.now())
    picam2.start_recording(encoder, FileOutput(output), quality=Quality.VERY_HIGH)


def stop_cam():
    logging.info("Cam stopped - %s!", datetime.now())
    picam2.stop_recording()


encoder = MJPEGEncoder()
picam2 = Picamera2()
picam2.configure(
    picam2.create_video_configuration(transform=Transform(hflip=True, vflip=True))
)
output = StreamingOutput()

try:
    address = ("", 8000)
    server = StreamingServer(address, StreamingHandler)
    server.serve_forever()
finally:
    logging.info("server stopped")
    stop_cam()
