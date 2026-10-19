# Spartan Browser 💪  
  
A `spartan://` protocol browser for MicroPythonOS. Browse the smolnet —  
gemtext documents served over raw TCP port 300 — with clickable links,  
upload prompts, and back navigation.  
  
Spartan is a client-to-server protocol that draws on Gemini, Gopher, and  
HTTP: a single ASCII request line (`host SP path SP content-length  
CRLF`) followed by an optional data block. No TLS, no headers, no  
cookies — just text and bytes.  
  
## Features  
  
- **Gemtext rendering** — headings (`#`/`##`/`###`), links (`=>`),  
  prompts (`=:`), lists (`*`), quotes (`>`), and preformatted blocks  
  (` ``` `).  
- **Upload prompts** — `=:` lines open an input dialog; the entered  
  text becomes the request `data-block`.  
- **Navigation** — address bar, back button, and in-page history.  
  Relative, absolute-path, and full `spartan://` links all resolve.  
- **Foreign schemes** — `gemini://`, `https://`, etc. inside documents  
  are handed to the system deeplink dispatcher so any registered app  
  can handle them.  
- **Deep links** — declares a `view_url` intent filter with  
  `urlPattern` `spartan://*` in `MANIFEST.JSON`, so Spartan URLs opened  
  via `deeplink.open_url()` launch straight into this app.  
- **Redirect following** — status `3` re-requests the returned  
  absolute path on the same host (spec-mandated; cross-host redirects  
  are not possible by design).  
  
## Status codes  
  
| Code | Meaning      | Behaviour                                    |  
|------|--------------|----------------------------------------------|  
| `2`  | Success      | Body rendered per mimetype (`text/gemini` default) |  
| `3`  | Redirect     | Same-host absolute path followed automatically |  
| `4`  | Client error | Error message shown in the status line       |  
| `5`  | Server error | Error message shown in the status line       |  
  
## URL handling  
  
The parser implements the spec's URL→request mapping:  
  
- Default port is **300**; `userinfo@` and `#fragment` are ignored.  
- Bare host (no port) is sent in the request line; the port only  
  affects the TCP connection.  
- `?query` is %-decoded and becomes the request `data-block`  
  (`?a=1&b=2` → `content-length 7`, body `a=1&b=2`).  
- Non-ASCII paths are UTF-8 %-encoded; IDN hosts are punycode-encoded  
  where the `idna` codec is available.  
  
## Architecture

internal_filesystem/
├── lib/mpos/net/spartan.py # protocol client (UI-free, testable)
└── apps/com.micropythonos.spartan/
├── MANIFEST.JSON # launcher + view_url intent filters
└── assets/spartan_app.py # SpartanBrowser Activity

  
### `mpos/net/spartan.py`  
  
- `parse_url(url)` → `{"host", "port", "path", "data"}` or `None`.  
  No LVGL imports — desktop-testable.  
- `await request(host, path="/", data=b"", port=300, timeout=15,  
  max_redirects=5, chunk_callback=None)` → `(status, meta, body)`.  
- `await fetch(url, **kwargs)` — URL convenience wrapper.  
- DNS is warmed via `getaddrinfo_async()` before  
  `asyncio.open_connection()` so lookups don't stall the LVGL event  
  loop; connect and the status-line read are bounded by  
  `asyncio.wait_for()`.  
- Pass `chunk_callback` to stream large binary bodies chunk-by-chunk  
  instead of buffering the whole response in RAM (important on ESP32).  
  
### `spartan_app.py`  
  
`SpartanBrowser(Activity)` builds an LVGL UI in `onCreate`: navigation  
bar (back / address / go), status line, and a scrollable content  
column. Network I/O runs off the UI thread via  
`TaskManager.create_task()`, and results are marshalled back with  
`update_ui_threadsafe_if_foreground()`.  
  
## Installing  
  
```sh  
./scripts/install.sh com.micropythonos.spartan  
```

then run AppManager.refresh_apps() on the device, or deploy the files
with mpremote cp and machine.reset().
Testing

The URL parser is pure Python and desktop-testable — exercise it
against the spec's mapping table (spartan://examplé.com/ →
xn--exampl-dma.com / 0, etc.). For end-to-end tests, a local TCP
stub returning canned 2/3/4/5 status lines exercises
request() without real network access.
Known limitations

Binary (non-text/*) bodies are reported but not saved — wiring
chunk_callback to a file writer is future work.
Punycode encoding for IDN hosts requires the idna codec; on builds
without it, non-ASCII hosts pass through unencoded.
Large uploads buffer data in RAM; no streaming request bodies yet.

### Protocol

Spec: The Spartan Protocol Specification (2021-03-24),
spartan://spartan.mozz.us. Default home page: spartan://spartan.mozz.us/
