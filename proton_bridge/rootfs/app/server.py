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
import hashlib
_index = Path(__file__).with_name("index.html").read_bytes()
UI_VERSION = hashlib.sha256(_index).hexdigest()[:12]
INDEX = _index.replace(b"__UI_VERSION__", UI_VERSION.encode())
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][A-Za-z0-9]|\x1b[=>]")
SGR = re.compile(r"\x1b\[[0-9;]*m")
NON_SGR = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-ln-~]|\x1b\[[0-9;]*\?[0-9;]*m|\x1b[()][A-Za-z0-9]|\x1b[=>]")
STATUS_LIST = "list "  # the page's own status polls; the trailing space marks them so the console can hide them

LOGIN_PATTERNS = {
    "need_2fa": "Two factor code: ",
    "need_mailbox": "Mailbox password: ",
    "need_hv": "Human Verification requested",
    "key_choice": "Do you want to use a security key",
    "need_key": "security key",
    "done": "was added successfully",
    "error": "Cannot login",
    "too_many": "Too many attempts",
    "prompt": ">>> ",
}


def _drop_visible(raw, n):
    """Drop the first n visible characters of raw, keeping the colour codes that are in effect."""
    i = seen = 0
    codes = ""
    while i < len(raw) and seen < n:
        m = SGR.match(raw, i)
        if m:
            codes += m.group(0)
            i = m.end()
        else:
            i += 1
            seen += 1
    return codes + raw[i:]


class Bridge:
    def __init__(self):
        self.lock = threading.RLock()
        self.proc_lock = threading.Lock()
        self.settings_cache = None
        self.console_waiting = False  # the console left Bridge waiting for an answer
        self.buf = self.rawbuf = ""
        self.fd = None
        self.pid = None
        self.login_state = "idle"  # idle | need_2fa | need_mailbox | need_hv
        self.hv_url = None
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
        self.ready = False  # until Bridge has loaded and answered its first "list"
        self.cache = {"accounts": None, "time": 0}

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
            self.buf = self.rawbuf = ""
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
                    self.buf = self.rawbuf = ""
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
            raw = data.decode("utf-8", "replace").replace("\r", "").replace("\b", "")
            self.buf = (self.buf + ANSI.sub("", raw))[-300_000:]
            # Display copy for the Console: keeps colours (SGR codes) only.
            self.rawbuf = (self.rawbuf + NON_SGR.sub("", raw))[-300_000:]

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
        if not self.ready and ">>> " not in self.buf:
            return None  # Bridge is still starting
        if self.login_state != "idle" or self.console_waiting or not self.lock.acquire(timeout=1):
            return self.cache["accounts"]
        try:
            out = self.command(STATUS_LIST)
        finally:
            self.lock.release()
        if "No active accounts" not in out and "address mode" not in out and not re.search(r"^\s*\d+\s*:", out, re.M):
            return self.cache["accounts"] if self.ready else None
        self.ready = True
        self._apply_defaults()
        accounts = []
        for m in re.finditer(r"^\s*(\d+)\s*:\s*(\S+)\s+\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)", out, re.M):
            accounts.append({"index": int(m.group(1)), "name": m.group(2),
                             "state": m.group(3), "mode": m.group(4)})
        self.cache = {"accounts": accounts, "time": time.time()}
        return accounts

    def _apply_defaults(self):
        """First start only: Bridge can't install updates in this app, so don't let it download them."""
        flag = Path(os.environ.get("HOME", "/data/home")) / ".ui-defaults-applied"
        if flag.exists():
            return
        try:
            with self.lock:
                self.confirm("updates autoupdates disable", "yes")
            flag.touch()
            self.settings_cache = None
        except Exception as err:  # retried on the next start
            print("Could not apply defaults:", err, flush=True)

    def sync(self):
        lines = [l.lstrip("> ") for l in self.buf.splitlines()]
        lines = [l for l in lines if l.startswith(("Sync (", "A sync has"))]
        if not lines:
            return None
        last = lines[-1]
        if "has finished" in last:
            return {"done": True}
        m = re.search(r"([\d.]+)%", last)
        eta = re.search(r"ETA: ([\d.]+)s", last)
        elapsed = re.search(r"Elapsed: ([\d.]+)s", last)
        if not elapsed or float(elapsed.group(1)) < 30:
            eta = None  # Bridge's estimate is meaningless right after (re)starting
        return {"done": False, "percent": float(m.group(1)) if m else 0.0,
                "eta": float(eta.group(1)) if eta else None}

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
            return {"state": "error", "message": "Your account only allows a hardware security key for two-factor sign-in. Bridge can "
                    "only use one plugged into this Home Assistant machine. Add an authenticator app as a "
                    "second method in your Proton account, then sign in again."}
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

    def wait_login(self, patterns, mark, timeout):
        """Wait for the next sign-in step; choose the authenticator app when Bridge offers a security key."""
        while True:
            key, seg = self.wait_for(patterns, mark, timeout)
            if key != "key_choice":
                return key, seg
            mark = len(self.buf)
            self.send("no")
            # Skip the line editor redrawing the question while it echoes the answer.
            end = time.time() + 10
            while "\n" not in self.buf[mark:] and time.time() < end:
                time.sleep(0.1)
            mark += self.buf[mark:].find("\n") + 1

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
            key, seg = self.wait_login(LOGIN_PATTERNS, mark, 90)
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
            key, seg = self.wait_login(patterns, mark, 90)
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
            imap, smtp = self._security()
            values["imap_ssl"] = None if imap is None else imap == "SSL"
            values["smtp_ssl"] = None if smtp is None else smtp == "SSL"
            self.settings_cache = values
        finally:
            self.lock.release()
        return values

    def _security(self):
        out = self.command("info 0")
        imap = re.search(r"IMAP Settings.*?Security:\s*(\S+)", out, re.S)
        smtp = re.search(r"SMTP Settings.*?Security:\s*(\S+)", out, re.S)
        return (imap.group(1).upper() if imap else None, smtp.group(1).upper() if smtp else None)

    def set_setting(self, key, on):
        if not self.lock.acquire(timeout=3):
            raise RuntimeError("Bridge is busy right now. Try again in a moment.")
        try:
            if key in ("imap_ssl", "smtp_ssl"):
                imap, smtp = self._security()
                current = imap if key == "imap_ssl" else smtp
                if current and (current == "SSL") != on:
                    self.confirm("change imap-security" if key == "imap_ssl" else "change smtp-security", "yes")
            else:
                on_cmd, off_cmd, _ = SETTINGS[key]
                self.confirm(on_cmd if on else off_cmd, "yes")
        finally:
            self.lock.release()
        if self.settings_cache:
            self.settings_cache[key] = on
        return {"ok": True}

    def account_action(self, action, index):
        cmd = {"logout": "logout", "delete": "delete", "mode": "change mode"}[action]
        _, out = self.confirm(f"{cmd} {int(index)}", "yes", timeout=60)
        # Ignore Bridge's own log lines (WARN[...], ERRO[...]); only its answers count.
        err = [l for l in out.splitlines() if l.lstrip(" >").startswith(("Cannot", "Logging out failed"))]
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
            out = seg[first_nl + 1:] if first_nl >= 0 else seg
            self.console_waiting = not out.rstrip().endswith(">>>")
            return out

    def send_raw(self, line):
        """Type one line into Bridge exactly as given (Console tab)."""
        if self.login_state != "idle":
            raise RuntimeError("Finish or cancel the sign-in first.")
        if not self.lock.acquire(timeout=5):
            raise RuntimeError("Bridge is busy right now. Try again in a moment.")
        try:
            mark = len(self.buf)
            self.send(line)
            self.wait_for({"q": "yes/no: ", "p": "\n>>> ", "p2": "\n >>> ", "c": ": "}, mark, 3)
            tail = self.buf[-200:].rstrip(" ")
            # Bridge is waiting for an answer: keep the page's own commands out of the way.
            self.console_waiting = not tail.endswith(">>>")
        finally:
            self.lock.release()
        return {"ok": True}

    def transcript(self):
        """Bridge's terminal as the Console shows it: colours kept, the line editor's redraws
        collapsed, and the page's own status polls and sync progress left out."""
        out, skipping = [], False
        for raw in self.rawbuf[-150_000:].split("\n"):
            plain = SGR.sub("", raw)
            for token in (">>> ", "yes/no: "):
                first = plain.find(token)
                if first >= 0:
                    prefix = plain[:first + len(token)]
                    cut = plain.rfind(prefix)
                    raw, plain = _drop_visible(raw, cut), plain[cut:]
                    break
            body = plain.lstrip("> ").strip()
            if plain.startswith(">>> "):
                skipping = plain[4:] == STATUS_LIST  # hide this poll and its output
            if skipping and not plain.startswith(">>> "):
                continue
            if skipping:
                continue
            if body.startswith(("Sync (", "A sync has")):
                continue
            out.append(raw)
        return "\n".join(out)

    def check_updates(self):
        with self.lock:
            mark = len(self.buf)
            self.send("updates check")
            key, seg = self.wait_for({"p": "\n>>> ", "p2": "\n >>> "}, mark, 30)
            time.sleep(1)
            seg = self.buf[mark:]
        lines = [l.strip(" >") for l in seg.splitlines()[1:] if l.strip(" >")]
        return " ".join(lines) or "No answer from Proton's update server."

    def factory_reset(self):
        with self.lock:
            self.confirm("clear everything", "yes", timeout=60)
        self.settings_cache = None
        self.restart()
        return {"ok": True}

    def imap_security(self, ssl=None):
        """Read (and optionally set) Bridge's IMAP security. Home Assistant's IMAP needs SSL."""
        if self.login_state != "idle":
            raise RuntimeError("Finish or cancel the sign-in first.")
        with self.lock:
            out = self.command("info 0")
            m = re.search(r"IMAP Settings.*?Security:\s*(\S+)", out, re.S)
            current = m.group(1).upper() if m else None
            if ssl is not None and current and (current == "SSL") != ssl:
                self.confirm("change imap-security", "yes")
                current = "SSL" if ssl else "STARTTLS"
        return current


SETTINGS = {
    "all_mail": ("all-mail-visibility show", "all-mail-visibility hide", "Show the All Mail folder"),
    "proxy": ("proxy allow", "proxy disallow", "Alternative routing"),
    "telemetry": ("telemetry enable", "telemetry disable", "Usage diagnostics"),
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
            self._json({"text": bridge.transcript()})
        elif path == "/api/status":
            self._json({"ui": UI_VERSION, "accounts": bridge.accounts(), "sync": bridge.sync(),
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
            elif path == "/api/check-updates":
                self._json({"message": bridge.check_updates()})
            elif path == "/api/factory-reset":
                self._json(bridge.factory_reset())
            elif path == "/api/imap-security":
                self._json({"security": bridge.imap_security(data.get("ssl"))})
            elif path == "/api/repair":
                self._json(bridge.repair())
            elif path == "/api/restart":
                bridge.restart()
                self._json({"ok": True})
            elif path == "/api/console":
                self._json(bridge.send_raw(clean(data.get("line"), 512)))
            else:
                self.send_error(404)
        except (ValueError, KeyError):
            self._json({"state": "error", "message": "That input isn't valid."}, 400)
        except RuntimeError as err:
            self._json({"state": "error", "message": str(err)}, 409)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
