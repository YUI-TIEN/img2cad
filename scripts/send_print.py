#!/usr/bin/env python3
"""Send a sliced file to a network printer, and optionally start it.

    img2cad send model.gcode --printer octoprint --host 192.168.1.20            # upload only
    img2cad send model.gcode --printer octoprint --host 192.168.1.20 --start    # upload and print
    img2cad send model.bgcode --printer prusalink --host 192.168.1.21 --start
    img2cad send model.gcode --printer moonraker --host klipper.local --start   # Klipper / Mainsail / Fluidd
    img2cad send plate.gcode.3mf --printer bambu --host 192.168.1.30 --serial 01P00A... --start

Credentials come from the environment, never the command line or a file in
the repository: IMG2CAD_PRINTER_KEY is the OctoPrint / PrusaLink / Moonraker
API key (Moonraker often needs none), or the Bambu printer's LAN access code.

Bambu printers must be in LAN mode (or LAN-only + developer mode on recent
firmware). The file goes over FTPS; `--start` publishes the print command
over MQTT and needs `pip install paho-mqtt`. Bambu needs a sliced
`.gcode.3mf` (export "plate sliced file" from Bambu Studio / OrcaSlicer, or
`img2cad slice ... --out plate.gcode.3mf`).

Upload is the default; printing starts only with `--start`. Check the plate,
filament and bed before you start a print you cannot watch.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import ssl
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import uuid

PRINTERS = ("octoprint", "prusalink", "moonraker", "bambu")


def _multipart(fields: dict[str, str], file_field: str, path: Path) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; filename=\"{path.name}\"\r\n"
                 "Content-Type: application/octet-stream\r\n\r\n".encode() + path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _base(host: str) -> str:
    return host.rstrip("/") if host.startswith(("http://", "https://")) else f"http://{host}"


def _request(url: str, method: str, body: bytes | None, headers: dict[str, str], timeout: float) -> tuple[int, str]:
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"{method} {url} -> HTTP {error.code}: {error.read().decode('utf-8', 'replace')[:300]}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"cannot reach {url}: {error.reason}") from error


def send_octoprint(path: Path, host: str, key: str | None, start: bool, timeout: float) -> dict[str, Any]:
    body, content_type = _multipart({"select": "true" if start else "false", "print": "true" if start else "false"}, "file", path)
    headers = {"Content-Type": content_type}
    if key:
        headers["X-Api-Key"] = key
    status, text = _request(f"{_base(host)}/api/files/local", "POST", body, headers, timeout)
    return {"status": status, "response": text[:500]}


def send_prusalink(path: Path, host: str, key: str | None, start: bool, timeout: float, storage: str = "usb") -> dict[str, Any]:
    headers = {"Content-Type": "application/octet-stream", "Overwrite": "?1", "Print-After-Upload": "?1" if start else "?0"}
    if key:
        headers["X-Api-Key"] = key
    url = f"{_base(host)}/api/v1/files/{storage}/{urllib.parse.quote(path.name)}"
    status, text = _request(url, "PUT", path.read_bytes(), headers, timeout)
    return {"status": status, "response": text[:500]}


def send_moonraker(path: Path, host: str, key: str | None, start: bool, timeout: float) -> dict[str, Any]:
    body, content_type = _multipart({"root": "gcodes", "print": "true" if start else "false"}, "file", path)
    headers = {"Content-Type": content_type}
    if key:
        headers["X-Api-Key"] = key
    status, text = _request(f"{_base(host)}/server/files/upload", "POST", body, headers, timeout)
    return {"status": status, "response": text[:500]}


def send_bambu(path: Path, host: str, access_code: str | None, serial: str | None, start: bool, timeout: float,
               plate: int = 1) -> dict[str, Any]:
    import ftplib

    if not access_code:
        raise RuntimeError("Bambu needs the printer's LAN access code in IMG2CAD_PRINTER_KEY")
    if not path.name.endswith(".3mf"):
        raise RuntimeError("Bambu printers take a sliced .gcode.3mf (export the plate sliced file)")

    class ImplicitFTPS(ftplib.FTP_TLS):  # Bambu uses implicit TLS on port 990
        def connect(self, host="", port=0, timeout=-999, source_address=None):
            sock = super().connect(host, port, timeout, source_address)
            self.sock = self.context.wrap_socket(self.sock, server_hostname=self.host)
            self.file = self.sock.makefile("r", encoding=self.encoding)
            return sock

        def ntransfercmd(self, cmd, rest=None):
            conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
            return self.context.wrap_socket(conn, server_hostname=self.host, session=self.sock.session), size

    context = ssl.create_default_context()
    context.check_hostname, context.verify_mode = False, ssl.CERT_NONE  # the printer's certificate is self-signed
    ftp = ImplicitFTPS(context=context, timeout=timeout)
    ftp.connect(host, 990)
    ftp.login("bblp", access_code)
    ftp.prot_p()
    with path.open("rb") as handle:
        ftp.storbinary(f"STOR {path.name}", handle)
    ftp.quit()
    report: dict[str, Any] = {"uploaded": path.name}
    if not start:
        return report
    if not serial:
        raise RuntimeError("--start on Bambu needs --serial (the printer's serial number)")
    try:
        import paho.mqtt.client as mqtt
    except ImportError as error:
        raise RuntimeError(f"uploaded {path.name}; starting needs paho-mqtt (pip install paho-mqtt), or start it on the printer") from error
    command = {"print": {"sequence_id": "0", "command": "project_file", "param": f"Metadata/plate_{plate}.gcode",
                         "url": f"file:///sdcard/{path.name}", "subtask_name": path.name, "use_ams": True,
                         "timelapse": False, "bed_leveling": True, "flow_cali": False, "vibration_cali": True, "layer_inspect": False}}
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2) if hasattr(mqtt, "CallbackAPIVersion") else mqtt.Client()
    client.username_pw_set("bblp", access_code)
    client.tls_set(cert_reqs=ssl.CERT_NONE)
    client.tls_insecure_set(True)
    client.connect(host, 8883, keepalive=30)
    client.loop_start()
    info = client.publish(f"device/{serial}/request", json.dumps(command), qos=1)
    info.wait_for_publish(timeout)
    client.loop_stop()
    client.disconnect()
    report["started"] = True
    return report


def send(path: Path, printer: str, host: str, start: bool = False, serial: str | None = None, timeout: float = 120,
         key: str | None = None, storage: str = "usb", plate: int = 1) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"{path} does not exist")
    key = key if key is not None else os.environ.get("IMG2CAD_PRINTER_KEY")
    if printer == "octoprint":
        result = send_octoprint(path, host, key, start, timeout)
    elif printer == "prusalink":
        result = send_prusalink(path, host, key, start, timeout, storage)
    elif printer == "moonraker":
        result = send_moonraker(path, host, key, start, timeout)
    elif printer == "bambu":
        result = send_bambu(path, host, key, serial, start, timeout, plate)
    else:
        raise RuntimeError(f"unknown printer {printer!r}; choose from {', '.join(PRINTERS)}")
    return {"printer": printer, "host": host, "file": path.name, "start": start, **result}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", type=Path, help=".gcode / .bgcode, or .gcode.3mf for Bambu")
    parser.add_argument("--printer", choices=PRINTERS, required=True)
    parser.add_argument("--host", required=True, help="printer address (IP, hostname or URL)")
    parser.add_argument("--start", action="store_true", help="start printing after the upload")
    parser.add_argument("--serial", help="Bambu: printer serial number (for --start)")
    parser.add_argument("--plate", type=int, default=1, help="Bambu: plate number in the 3MF")
    parser.add_argument("--storage", default="usb", help="PrusaLink storage (usb or local)")
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    try:
        report = send(args.file, args.printer, args.host, args.start, args.serial, args.timeout, storage=args.storage, plate=args.plate)
    except (RuntimeError, OSError) as error:
        parser.exit(2, f"FAIL: {error}\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
