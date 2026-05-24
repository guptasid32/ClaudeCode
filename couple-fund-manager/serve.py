#!/usr/bin/env python3
"""LAN-accessible server for the Couple Fund Manager.

Serves the static UI AND persists shared state on the laptop in data.json,
so every device on the same Wi-Fi reads and writes the same data.

Run this from the couple-fund-manager directory:

    python3 serve.py                       # default port 8080, ./data.json
    python3 serve.py 5000                  # custom port
    python3 serve.py 5000 /path/to/data.json   # custom data file

API (used by the UI):
    GET  /api/state             ->  {"state": {...}, "version": N}
    PUT  /api/state             ->  body {"state": {...}}  ; returns {"version": N}
    DELETE /api/state           ->  wipes data.json
    GET  /api/categorize/status ->  {"available": bool, "reason"?: str, "model": str}
    POST /api/categorize        ->  body {"transactions":[{id,description},...], "categories":[...]}
                                    returns {"results": {id: category, ...}}

For AI categorization:
    pip install anthropic
    export ANTHROPIC_API_KEY=sk-ant-...
Then restart the server. The key stays on the laptop; the browser never sees it.
"""

import http.server
import json
import os
import socket
import socketserver
import sys
import tempfile
import threading
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
HOST = "0.0.0.0"
ROOT = Path(__file__).resolve().parent
DATA_PATH = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else (ROOT / "data.json")

_lock = threading.Lock()
_version = 0  # monotonically increases on every successful write


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _read_state() -> dict:
    if not DATA_PATH.exists():
        return {}
    try:
        with DATA_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


# ---------- AI categorization (Claude API) ----------
# Haiku 4.5 is the right tool for this job: short-string classification is
# exactly what it's designed for, and it runs ~$0.001 per 50-row statement.
# Swap to "claude-opus-4-7" if you want maximum accuracy at ~50x the cost.
CATEGORIZE_MODEL = "claude-haiku-4-5"

_categorize_system_prompt = """\
You are a bank transaction categorizer for an Indian personal-finance app.

Given a list of transaction descriptions copied verbatim from a bank statement,
classify each one into exactly one of the categories provided in the user's
request. Return JSON with a `categorizations` array containing one
{id, category} object per input transaction. Use only the supplied category
values; do not invent new ones.

Tips for common Indian-bank descriptions:
- UPI/SWIGGY, ZOMATO, FAASOS, restaurant, cafe         -> Food & Dining
- BIGBASKET, DMART, BLINKIT, ZEPTO, INSTAMART, grocery -> Groceries
- UBER, OLA, RAPIDO, IRCTC, METRO, fuel, petrol,
  BPCL, IOCL, HPCL, INDIANOIL, FASTAG, parking          -> Transport
- ELECTRICITY, BESCOM, MSEDCL, TNEB, KSEB, water bill,
  gas bill, AIRTEL, JIO, broadband, ACT FIBERNET,
  mobile recharge, DTH                                  -> Utilities
- RENT, MAINTENANCE, society                            -> Rent & Housing
- AMAZON, FLIPKART, MYNTRA, AJIO, MEESHO, NYKAA,
  TATA CLIQ, IKEA, DECATHLON, retail purchases          -> Shopping
- NETFLIX, PRIME VIDEO, SPOTIFY, HOTSTAR, SONY LIV,
  ZEE5, BOOKMYSHOW, PVR, INOX, movie                    -> Entertainment
- PHARMACY, APOLLO, 1MG, PHARMEASY, NETMEDS, MEDPLUS,
  hospital, doctor, clinic, diagnostic                  -> Health
- UDEMY, COURSERA, BYJUS, UNACADEMY, tuition,
  school fees, college fees                             -> Education
- SIP, mutual fund, ZERODHA, GROWW, KUVERA, UPSTOX,
  LIC premium, PPF, NPS, ELSS, ICICIDIRECT              -> Investments
- SALARY credit, REIMBURSEMENT, REFUND, CASHBACK,
  INTEREST CREDIT, DIVIDEND                             -> Income
- NEFT TO, IMPS TO, RTGS TO, UPI TO <person>, transfer  -> Transfers
- ATM, CASH WITHDRAWAL, CASH WDL                        -> Cash
- Bank charges, annual fee, GST, late fee, penalty,
  overdraft fee, FX markup                              -> Fees & Charges
- If the description is genuinely ambiguous or doesn't
  match anything above                                  -> Other

A few gotchas:
- "UPI TO <merchant>" patterns are NOT transfers; classify by the merchant.
- "BY TRANSFER NEFT-RENT" is Rent & Housing, not Transfers.
- "INTEREST CREDIT" / "INT CR" from the bank is Income, not Investments.
- An ATM withdrawal at any bank is Cash, not Transfers.
- "POS" prefix just means card-swipe; classify by the merchant after it.
- Salary deposits often look like "NEFT/SALARY/<COMPANY>" or "SAL CR".
- Don't classify by amount; rely only on the description text.

Be decisive. Return the categorization for every transaction in the input,
preserving the original `id` exactly. Do not add commentary outside the JSON.
"""


def _ai_available() -> tuple[bool, str | None]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False, "ANTHROPIC_API_KEY environment variable is not set."
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False, "The 'anthropic' Python package is not installed. Run: pip install anthropic"
    return True, None


def _categorize_via_claude(transactions: list[dict], categories: list[str]) -> dict[str, str]:
    """Send a batch of transactions to Claude and return {id: category}."""
    import anthropic

    client = anthropic.Anthropic()

    # Output schema constrains every category to one of the allowed values,
    # so the model can't invent new buckets.
    schema = {
        "type": "object",
        "properties": {
            "categorizations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "category": {"type": "string", "enum": categories},
                    },
                    "required": ["id", "category"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["categorizations"],
        "additionalProperties": False,
    }

    # cache_control is harmless if the prompt is below the cacheable minimum
    # for Haiku (4096 tokens); on Opus it'll cache the system prompt across
    # repeated statement uploads in the same session.
    response = client.messages.create(
        model=CATEGORIZE_MODEL,
        max_tokens=4096,
        system=[{
            "type": "text",
            "text": _categorize_system_prompt,
            "cache_control": {"type": "ephemeral"},
        }],
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{
            "role": "user",
            "content": (
                f"Classify these {len(transactions)} transactions. "
                f"Allowed categories: {', '.join(categories)}.\n\n"
                + json.dumps({"transactions": transactions}, ensure_ascii=False)
            ),
        }],
    )

    text = next(b.text for b in response.content if getattr(b, "type", None) == "text")
    parsed = json.loads(text)
    out: dict[str, str] = {}
    for item in parsed.get("categorizations", []):
        if isinstance(item, dict) and "id" in item and "category" in item:
            out[str(item["id"])] = str(item["category"])
    return out


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/state":
            with _lock:
                self._send_json(200, {"state": _read_state(), "version": _version})
            return
        if self.path == "/api/categorize/status":
            ok, reason = _ai_available()
            payload = {"available": ok, "model": CATEGORIZE_MODEL}
            if reason:
                payload["reason"] = reason
            self._send_json(200, payload)
            return
        return super().do_GET()

    def do_PUT(self):
        if self.path == "/api/state":
            global _version
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                self._send_json(400, {"error": f"Invalid JSON: {e}"})
                return
            state = payload.get("state", payload)
            if not isinstance(state, dict):
                self._send_json(400, {"error": "state must be a JSON object"})
                return
            with _lock:
                try:
                    _atomic_write(DATA_PATH, json.dumps(state, indent=2).encode("utf-8"))
                    _version += 1
                    self._send_json(200, {"version": _version})
                except OSError as e:
                    self._send_json(500, {"error": str(e)})
            return
        self.send_error(404)

    def do_POST(self):
        if self.path == "/api/categorize":
            ok, reason = _ai_available()
            if not ok:
                self._send_json(503, {"error": reason})
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                self._send_json(400, {"error": f"Invalid JSON: {e}"})
                return
            txns = payload.get("transactions")
            cats = payload.get("categories")
            if not isinstance(txns, list) or not txns:
                self._send_json(400, {"error": "transactions must be a non-empty array"})
                return
            if not isinstance(cats, list) or not cats:
                self._send_json(400, {"error": "categories must be a non-empty array"})
                return
            if len(txns) > 500:
                self._send_json(400, {"error": "max 500 transactions per request"})
                return
            cleaned = []
            for t in txns:
                if not isinstance(t, dict):
                    continue
                tid = str(t.get("id", "")).strip()
                desc = str(t.get("description", "")).strip()
                if tid and desc:
                    cleaned.append({"id": tid, "description": desc[:200]})
            if not cleaned:
                self._send_json(400, {"error": "no valid transactions in request"})
                return
            try:
                results = _categorize_via_claude(cleaned, [str(c) for c in cats])
            except Exception as e:
                # surface the error message so the UI can show something useful
                self._send_json(502, {"error": f"Claude API call failed: {e}"})
                return
            self._send_json(200, {"results": results, "model": CATEGORIZE_MODEL})
            return
        self.send_error(404)

    def do_DELETE(self):
        if self.path == "/api/state":
            global _version
            with _lock:
                try:
                    if DATA_PATH.exists():
                        DATA_PATH.unlink()
                    _version += 1
                    self._send_json(200, {"version": _version})
                except OSError as e:
                    self._send_json(500, {"error": str(e)})
            return
        self.send_error(404)

    def log_message(self, fmt, *args):
        # Quieter than default; only log non-asset paths.
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/") or path in {"/"}:
            sys.stderr.write(
                "%s - %s\n" % (self.log_date_time_string(), fmt % args)
            )


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def lan_addresses():
    addrs = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ip = info[4][0]
            if ":" in ip or ip.startswith("127."):
                continue
            addrs.add(ip)
    except socket.gaierror:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            addrs.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(addrs)


def main():
    global _version
    if DATA_PATH.exists():
        _version = 1  # any starting version > 0 indicates "data exists"
    with _Server((HOST, PORT), Handler) as httpd:
        print(f"Couple Fund Manager")
        print(f"  Static dir:  {ROOT}")
        print(f"  Data file:   {DATA_PATH}")
        print(f"  Local:       http://localhost:{PORT}/")
        for ip in lan_addresses():
            print(f"  Wi-Fi:       http://{ip}:{PORT}/")
        print("Press Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
