# mpos.net.spartan_server — spartan:// server  
  
An asyncio server speaking the Spartan protocol (spec 2021-03-24):  
one ASCII request line `host SP path SP content-length CRLF` plus an  
optional data-block in; a single-digit status line (`2`/`3`/`4`/`5`)  
plus an optional body out. Listens on TCP port **300** by default.  
  
Everything runs on the TaskManager event loop via  
`asyncio.start_server` — no blocking accept loop, so the LVGL UI never  
stalls (unlike `mpos.webserver.webrepl`, which uses a socket  
accept-handler). No LVGL or hardware imports; the module is  
desktop-testable.  
  
## Usage  
  
```python  
from mpos import TaskManager  
from mpos.net.spartan_server import SpartanServer  
  
srv = SpartanServer("/data/myapp/spartan", port=300)  
TaskManager.create_task(srv.serve())  
# ... later:  [header-2](#header-2)
srv.stop()

API
SpartanServer(docroot, port=300, host="0.0.0.0", upload_handler=None, index_files=("index.gmi", "index.txt"))

    docroot — filesystem path whose contents are served. Request paths
    are %-decoded and normalized; .. traversal outside docroot is
    rejected with status 4.
    upload_handler — async def handler(host, path, data) called when
    a request carries a data-block (content-length > 0). Must return
    (status:int, meta:str, body:bytes|None). If None, upload
    requests get 4 "This resource accepts no data". The data-block
    format is server-defined per the spec — use it for guestbooks, file
    uploads, etc.
    index_files — filenames tried in order for directory requests.

await serve() / stop()

serve() binds and serves until stop() is called or the task is
cancelled. Schedule it with TaskManager.create_task() — or
TaskManager.create_supervised_task() for crash-restart resilience,
the same supervision AIOReplService uses.
Behaviour
Request	Response
GET file (length = 0)	2 <mimetype> + body streamed in 4 KB chunks
Directory without trailing /	3 <path/> (same-host redirect)
Directory with /, index exists	2 serving the index file
File not found / bad syntax / .. escape	4 + human-readable message
Data-block > 64 KB (MAX_DATA_BLOCK)	4 "Data block too large"
Internal fault	5 "Internal server error"
Idle client > 30 s (READ_TIMEOUT_S)	4 "Request timed out"

MIME types are mapped from file extension (.gmi → text/gemini,
.txt → text/plain, etc.); unknown types fall back to
application/octet-stream.
Memory & limits

Bodies are streamed — writer.write/drain per 4 KB chunk — so
large files don't need to fit in RAM (important on ESP32). The request
line is capped at 512 bytes (MAX_REQUEST_LINE) and uploads at 64 KB
(MAX_DATA_BLOCK); tune per board.
Testing

tests/test_spartan_server.py runs a round trip on the desktop build:
it starts TaskManager on a _thread (same harness as
test_webserver.py), starts SpartanServer, and drives it with the
client from mpos.net.spartan — covering index serving, 404s,
uploads, and malformed request lines. Run with:

./scripts/test_runner.py tests/test_spartan_server.py

Boot autostart

To start at boot, add a boot_completed service in
mpos/app/system_services.py next to WebServerBootService, and gate
it behind SharedPreferences (autostart, port) following the
WebServer.auto_start() pattern in mpos/webserver/webserver.py.

  
---  
  
### `internal_filesystem/apps/com.micropythonos.spartanserver/README.md`  [header-3](#header-3)
  
```markdown  
# Spartan Server 💪  
  
Host your own `spartan://` capsule from a MicroPythonOS device. This  
config app creates a document root inside the app's own data folder,  
seeds it with a starter `index.gmi`, and starts/stops the server on a  
button press.  
  
## What it does  
  
1. **Create docroot** — `data/com.micropythonos.spartanserver/spartan/`  
   is created with:  
   - `index.gmi` — starter capsule page (links to `/files/` and a  
     `=:guestbook.txt` prompt)  
   - `guestbook.txt` — append-only target for prompt uploads  
   - `files/` — drop documents/media here to serve them  
2. **Start/Stop server** — launches `mpos.net.spartan_server.SpartanServer`  
   as an asyncio task on the TaskManager loop. No UI blocking.  
3. **Port** — configurable (default 300), persisted via  
   `SharedPreferences`.  
  
Once started, the capsule is reachable at  
`spartan://<device-ip>:<port>/` from any Spartan client (including the  
Spartan Browser app, `com.micropythonos.spartan`).  
  
## Uploads (`=:` prompts)  
  
Requests carrying a data-block are routed to the app's upload handler,  
which appends the raw bytes (one line, CRLF-normalized) to the file  
named by the request path inside the docroot — so  
`=:guestbook.txt` prompts become guestbook entries. Path traversal  
(`..`) is rejected. The handler returns `2 text/plain` with a short  
confirmation body; servers without a handler configured would get  
`4 "This resource accepts no data"`.  
  
## Files & storage  
  
| Path | Contents | Lifecycle |  
|---|---|---|  
| `data/com.micropythonos.spartanserver/spartan/` | Served docroot (index.gmi, files/, uploads) | User data; removed on uninstall |  
| `prefs/com.micropythonos.spartanserver/` | `port` preference | Removed on uninstall |  
  
The docroot lives in **app data**, not `builtin/` — so all files the  
server publishes are user-owned, survive reboots, and are cleaned up  
by `AppManager.uninstall_app` along with prefs and cache.  
  
## Architecture  
  

internal_filesystem/
├── lib/mpos/net/spartan_server.py # SpartanServer class (this app's engine)
├── lib/mpos/net/spartan.py # client (used by tests + browser app)
└── apps/com.micropythonos.spartanserver/
├── MANIFEST.JSON # launcher intent filter
└── spartan_server_app.py # SpartanServerConfig Activity

  
`SpartanServerConfig(Activity)` builds the LVGL UI in `onCreate`  
(title, port field, setup button, start/stop toggle, status label).  
Server tasks are scheduled via `TaskManager.create_task()`; the server  
is stopped in `onDestroy` so leaving the app doesn't leak the socket.  
  
## Installing  
  
```sh  
./scripts/install.sh com.micropythonos.spartanserver  

then AppManager.refresh_apps() on-device. The server engine also
needs lib/mpos/net/spartan_server.py deployed (a full install.sh
run covers lib/; single-file deploy:
mpremote cp internal_filesystem/lib/mpos/net/spartan_server.py :/lib/mpos/net/
then machine.reset()).
Protocol

Spec: The Spartan Protocol Specification (2021-03-24),
spartan://spartan.mozz.us. Default port 300. Status codes: 2
success, 3 same-host redirect, 4 client error, 5 server error.
Known limitations

    No TLS or authentication — Spartan is plaintext; don't serve private
    data on untrusted networks.
    Uploads are buffered in RAM, capped at 64 KB (MAX_DATA_BLOCK).
    Server lifetime is tied to the app; for boot autostart, register a
    boot_completed service (see WebServerBootService /
    NostrBootService for the pattern).
