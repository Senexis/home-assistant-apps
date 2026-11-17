#!/usr/bin/env python3
"""Small web UI for Proton Mail Bridge, served through Home Assistant Ingress.

Bridge runs as its own interactive CLI (`bridge --cli`) on a pseudo-terminal owned by
this process. The UI drives that CLI (login, list, info, logout) and reads its output.
Only Home Assistant's Ingress proxy may connect.
"""
import json
import os
import pty
import re
import select
import signal
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

INGRESS_IP = os.environ.get("UI_ALLOW_IP", "172.30.32.2")
PORT = 8099
IMAP_PORT = 9143
BRIDGE = os.environ.get("UI_BRIDGE", "/usr/local/bin/bridge --cli").split()
INDEX = Path(__file__).with_name("index.html").read_bytes()
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][A-Za-z0-9]|\x1b[=>]")

LOGIN_PATTERNS = {
    "need_2fa": "Two factor code: ",
    "need_mailbox": "Mailbox password: ",
    "need_hv": "Human Verification requested",
    "need_key": "security key",
    "done": "was added successfully",
    "error": "Cannot login",
    "too_many": "Too many attempts",
    "prompt": ">>> ",
}


class Bridge:
    def __init__(self):
        self.lock = threading.RLock()
        self.proc_lock = threading.Lock()
        self.settings_cache = None
        self.buf = ""
        self.fd = None
        self.pid = None
        self.login_state = "idle"  # idle | need_2fa | need_mailbox | need_hv
        self.hv_url = None
        self.cache = {"accounts": [], "time": 0}
        self.start()
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._watch, daemon=True).start()

    # --- process handling -------------------------------------------------
    def start(self):
        pid, fd = pty.fork()
        if pid == 0:
            os.environ["TERM"] = "dumb"
            os.execvp(BRIDGE[0], BRIDGE)
        self.pid, self.fd = pid, fd
        self.login_state, self.hv_url = "idle", None

    def _stop(self):
        """Stop the current Bridge and wait until it's really gone (it holds a lock file)."""
        pid = self.pid
        for sig, wait in ((signal.SIGTERM, 20), (signal.SIGKILL, 5)):
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
            end = time.time() + wait
            while time.time() < end:
                try:
                    done, _ = os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    return
                if done:
                    return
                time.sleep(0.2)

    def restart(self):
        with self.proc_lock:
            self._stop()
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.buf = ""
            self.start()

    def _watch(self):
        while True:
            time.sleep(2)
            with self.proc_lock:
                try:
                    done, _ = os.waitpid(self.pid, os.WNOHANG)
                except ChildProcessError:
                    done = self.pid
                if done:
                    print("Bridge exited, restarting in 5 seconds", flush=True)
                    time.sleep(5)
                    try:
                        os.close(self.fd)
                    except OSError:
                        pass
                    self.buf = ""
                    self.start()

    def _reader(self):
        while True:
            fd = self.fd
            try:
                r, _, _ = select.select([fd], [], [], 1)
                if not r:
                    continue
                data = os.read(fd, 65536)
            except OSError:
                time.sleep(1)
                continue
            text = ANSI.sub("", data.decode("utf-8", "replace")).replace("\r", "").replace("\b", "")
            self.buf = (self.buf + text)[-300_000:]

    # --- talking to the CLI -----------------------------------------------
    def send(self, line):
        os.write(self.fd, line.encode() + b"\r")

    def wait_for(self, patterns, mark, timeout):
        end = time.time() + timeout
        while time.time() < end:
            seg = self.buf[mark:]
            hits = [(seg.find(p), k) for k, p in patterns.items() if seg.find(p) >= 0]
            if hits:
                return min(hits)[1], seg
            time.sleep(0.2)
        return None, self.buf[mark:]

    def command(self, cmd, timeout=15):
        """Run a shell command and return its output (up to the next prompt)."""
        mark = len(self.buf)
        self.send(cmd)
        end = time.time() + timeout
        while time.time() < end:
            seg = self.buf[mark:]
            nl = seg.find("\n")
            if nl >= 0 and seg.find(">>> ", nl) >= 0:
                return seg[nl + 1: seg.find(">>> ", nl)]
            time.sleep(0.2)
        return self.buf[mark:]

    # --- features ------------------------------------------------------------
    def accounts(self):
        if self.login_state != "idle" or not self.lock.acquire(timeout=1):
            return self.cache["accounts"]
        try:
            out = self.command("list")
        finally:
            self.lock.release()
        accounts = []
        for m in re.finditer(r"^\s*(\d+)\s*:\s*(\S+)\s+\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)", out, re.M):
            accounts.append({"index": int(m.group(1)), "name": m.group(2),
                             "state": m.group(3), "mode": m.group(4)})
        self.cache = {"accounts": accounts, "time": time.time()}
        return accounts

    def sync(self):
        lines = [l for l in self.buf.splitlines() if l.startswith(("Sync (", "A sync has"))]
        if not lines:
            return None
        last = lines[-1]
        if "has finished" in last:
            return {"done": True}
        m = re.search(r"([\d.]+)%", last)
        return {"done": False, "percent": float(m.group(1)) if m else 0.0}

    def imap(self, index):
        with self.lock:
            out = self.command(f"info {int(index)}")
        m = re.search(r"IMAP Settings.*?Username:\s*(\S+).*?Password:\s*(\S+).*?Security:\s*(\S+)", out, re.S)
        if not m:
            return None
        return {"host": socket.gethostname(), "port": IMAP_PORT,
                "username": m.group(1), "password": m.group(2), "security": m.group(3)}

    def _login_result(self, key, seg):
        if key in ("need_2fa", "need_mailbox"):
            self.login_state = key
            return {"state": key}
        if key == "need_hv":
            time.sleep(1)  # the URL is printed just after the notice
            hv_text = self.buf[self.buf.rfind(LOGIN_PATTERNS["need_hv"]):]
            url = re.search(r"https://verify\.proton\.me/\S+", hv_text) or re.search(r"https://\S+", hv_text)
            self.hv_url = url.group(0) if url else None
            self.login_state = "need_hv"
            return {"state": "need_hv", "url": self.hv_url}
        if key == "need_key":
            self.restart()
            return {"state": "error", "message": "This account asks for a hardware security key, which "
                    "can't be used here. Add an authenticator app to your Proton account and try again."}
        self.login_state = "idle"
        if key == "done":
            return {"state": "done"}
        # Error, timeout or back at the prompt: report Bridge's own words.
        lines = [l.strip() for l in seg.splitlines()
                 if l.strip() and not l.startswith((">>>", "Password", "Mailbox password", "Two factor"))]
        msg = next((l for l in reversed(lines) if "login" in l.lower() or "error" in l.lower()),
                   lines[-1] if lines else "Sign-in didn't finish.")
        if key is None:
            self.restart()
            msg = "Bridge didn't answer in time. Please try again."
        return {"state": "error", "message": msg}

    def login(self, email, password):
        with self.lock:
            if self.login_state != "idle":
                self.restart()
            mark = len(self.buf)
            self.send("login")
            key, _ = self.wait_for({"u": "Username: "}, mark, 15)
            if not key:
                self.restart()
                return {"state": "error", "message": "Bridge isn't ready yet. Try again in a minute."}
            mark = len(self.buf)
            self.send(email)
            key, _ = self.wait_for({"p": "Password: "}, mark, 15)
            if not key:
                return self._login_result(None, "")
            mark = len(self.buf)
            self.send(password)
            key, seg = self.wait_for(LOGIN_PATTERNS, mark, 90)
            return self._login_result(key, seg)

    def answer(self, value):
        with self.lock:
            if self.login_state == "idle":
                return {"state": "error", "message": "There's no sign-in waiting for this."}
            mark = len(self.buf)
            self.send(value)
            patterns = dict(LOGIN_PATTERNS)
            if self.login_state == "need_2fa":
                patterns.pop("need_2fa")  # a wrong code ends the attempt with "Cannot login"
            key, seg = self.wait_for(patterns, mark, 90)
            return self._login_result(key, seg)

    def confirm(self, cmd, answer, timeout=30):
        """Run a command that may ask yes/no; answer it. Returns (asked, output)."""
        with self.lock:
            if self.login_state != "idle":
                raise RuntimeError("Finish or cancel the sign-in first.")
            mark = len(self.buf)
            self.send(cmd)
            # Skip the echoed command line before looking for the prompt.
            key, seg = self.wait_for({"q": "yes/no: ", "p": "\n>>> ", "p2": "\n >>> "}, mark, timeout)
            if key == "q":
                self.send(answer)
                _, seg = self.wait_for({"p": "\n>>> ", "p2": "\n >>> "}, mark, timeout)
            return key == "q", seg

    def settings(self, fresh=False):
        if self.settings_cache and not fresh:
            return self.settings_cache
        if self.login_state != "idle":
            raise RuntimeError("Finish or cancel the sign-in first.")
        if not self.lock.acquire(timeout=3):
            raise RuntimeError("Bridge is busy right now. Try again in a moment.")
        try:
            values = {}
            for key, (on_cmd, _off, _label) in SETTINGS.items():
                asked, _ = self.confirm(on_cmd, "no", timeout=10)
                values[key] = not asked  # "already ..." means it's on
            self.settings_cache = values
        finally:
            self.lock.release()
        return values

    def set_setting(self, key, on):
        on_cmd, off_cmd, _ = SETTINGS[key]
        if not self.lock.acquire(timeout=3):
            raise RuntimeError("Bridge is busy right now. Try again in a moment.")
        try:
            self.confirm(on_cmd if on else off_cmd, "yes")
        finally:
            self.lock.release()
        if self.settings_cache:
            self.settings_cache[key] = on
        return {"ok": True}

    def account_action(self, action, index):
        cmd = {"logout": "logout", "delete": "delete", "mode": "change mode"}[action]
        _, out = self.confirm(f"{cmd} {int(index)}", "yes", timeout=60)
        err = [l for l in out.splitlines() if "Cannot" in l or "failed" in l]
        return {"ok": not err, "message": err[-1].strip() if err else ""}

    def repair(self):
        _, out = self.confirm("repair", "yes")
        if "cannot connect" in out:
            return {"ok": False, "message": "Bridge can't reach Proton right now, so it can't repair."}
        return {"ok": True}

    def version(self):
        if getattr(self, "_version", None):
            return self._version
        with self.lock:
            out = self.command("version")
        m = re.search(r"Proton Mail Bridge (\S+)", out)
        self._version = m.group(1) if m else ""
        return self._version

    def console(self, line):
        """Send one line as typed and return what Bridge printed (max ~10 s)."""
        with self.lock:
            if self.login_state != "idle":
                raise RuntimeError("Finish or cancel the sign-in first.")
            mark = len(self.buf)
            self.send(line)
            _, seg = self.wait_for({"q": "yes/no: ", "p": "\n>>> ", "p2": "\n >>> ", "c": ": "}, mark, 10)
            time.sleep(0.3)
            seg = self.buf[mark:]
            first_nl = seg.find("\n")
            return seg[first_nl + 1:] if first_nl >= 0 else ""


SETTINGS = {
    "all_mail": ("all-mail-visibility show", "all-mail-visibility hide", "Show the All Mail folder"),
    "proxy": ("proxy allow", "proxy disallow", "Alternative routing"),
    "telemetry": ("telemetry enable", "telemetry disable", "Usage diagnostics"),
    "autoupdates": ("updates autoupdates enable", "updates autoupdates disable", "Automatic updates"),
}


bridge = Bridge()


def clean(value, limit=256):
    value = str(value or "")
    if len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("invalid input")
    return value


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # never log requests: bodies hold credentials

    def _allowed(self):
        if self.client_address[0] != INGRESS_IP:
            self.send_error(403)
            return False
        return True

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._allowed():
            return
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(INDEX)
        elif path == "/api/screen":
            self._json({"text": bridge.buf[-6000:]})
        elif path == "/api/status":
            self._json({"accounts": bridge.accounts(), "sync": bridge.sync(),
                        "login_state": bridge.login_state, "hv_url": bridge.hv_url})
        else:
            self.send_error(404)

    def do_POST(self):
        if not self._allowed():
            return
        try:
            length = min(int(self.headers.get("Content-Length", 0)), 4096)
            data = json.loads(self.rfile.read(length) or b"{}")
            path = self.path.split("?")[0]
            if path == "/api/login":
                self._json(bridge.login(clean(data.get("email")), clean(data.get("password"))))
            elif path == "/api/answer":
                self._json(bridge.answer(clean(data.get("value"))))
            elif path == "/api/cancel":
                bridge.restart()
                self._json({"state": "idle"})
            elif path == "/api/imap":
                info = bridge.imap(int(data.get("index", 0)))
                self._json(info or {"error": "Bridge has no connection details yet."}, 200 if info else 409)
            elif path == "/api/account":
                self._json(bridge.account_action(clean(data.get("action")), int(data.get("index", 0))))
            elif path == "/api/settings":
                if "key" in data:
                    self._json(bridge.set_setting(clean(data["key"]), bool(data.get("on"))))
                else:
                    self._json({"values": bridge.settings(), "version": bridge.version(),
                                "labels": {k: v[2] for k, v in SETTINGS.items()}})
            elif path == "/api/repair":
                self._json(bridge.repair())
            elif path == "/api/restart":
                bridge.restart()
                self._json({"ok": True})
            elif path == "/api/console":
                self._json({"output": bridge.console(clean(data.get("line"), 512))})
            else:
                self.send_error(404)
        except (ValueError, KeyError):
            self._json({"state": "error", "message": "That input isn't valid."}, 400)
        except RuntimeError as err:
            self._json({"state": "error", "message": str(err)}, 409)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
