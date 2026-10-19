"""spartan:// client for MicroPythonOS.  
  
Implements the Spartan protocol (spec 2021-03-24): a single ASCII  
request line "host SP path SP content-length CRLF" over raw TCP,  
default port 300, followed by an optional data-block.  
  
No LVGL or hardware imports at module level so this file is  
desktop-testable, like mpos.content.deeplink.  
"""  
"""
to be placed in internal_filesystem/lib/mpos/net/spartan.py
"""
import asyncio  
import logging  
  
logger = logging.getLogger(__name__)  
  
SCHEME = "spartan"  
DEFAULT_PORT = 300  
MAX_URL_LENGTH = 512  
MAX_REDIRECTS = 5  
READ_CHUNK = 4096  
  
_SCHEME_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789+.-"  
  
# Characters that may appear unencoded in a path segment (RFC 3986  
# pchar + '/').  
_PATH_SAFE = ("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"  
              "0123456789-._~!$&'()*+,;=:@/")  
  
  
def _quote_path(path):  
    """%-encode path bytes that are not ASCII-safe."""  
    out = []  
    for b in path.encode("utf-8"):  
        c = chr(b)  
        if c in _PATH_SAFE or c == "%":  # keep existing %XX escapes  
            out.append(c)  
        else:  
            out.append("%%%02X" % b)  
    return "".join(out)  
  
  
def _unquote(text):  
    """%-decode into bytes (the query becomes the data-block)."""  
    out = bytearray()  
    i = 0  
    raw = text.encode("utf-8")  
    while i < len(raw):  
        if raw[i:i+1] == b"%" and i + 2 < len(raw) + 1:  
            try:  
                out.append(int(raw[i+1:i+3], 16))  
                i += 3  
                continue  
            except (ValueError, IndexError):  
                pass  
        out.append(raw[i])  
        i += 1  
    return bytes(out)  
  
  
def _idna(host):  
    """Punycode-encode an IDN host; returns host unchanged if ASCII.  
  
    'idna' encoding exists on CPython/desktop builds; on targets  
    without it we leave the host as-is and let DNS fail naturally.  
    """  
    try:  
        host.encode("ascii")  
        return host  
    except UnicodeEncodeError:  
        pass  
    try:  
        return host.encode("idna").decode("ascii")  
    except (UnicodeError, LookupError):  
        logger.warning("no idna codec; passing non-ASCII host through")  
        return host  
  
  
def parse_url(url):  
    """Parse a spartan:// URL.  
  
    Returns dict(host, port, path, data) or None. 'path' is already  
    %-encoded for the request line; 'data' is the data-block bytes  
    derived from a %-decoded query component.  
    """  
    if not isinstance(url, str):  
        return None  
    url = url.strip()  
    if not url or len(url) > MAX_URL_LENGTH:  
        return None  
    sep = url.find("://")  
    if sep <= 0:  
        return None  
    scheme = url[:sep].lower()  
    if scheme != SCHEME:  
        return None  
    rest = url[sep + 3:]  
  
    frag = rest.find("#")  
    if frag != -1:  
        rest = rest[:frag]  
    query = ""  
    q = rest.find("?")  
    if q != -1:  
        query = rest[q + 1:]  
        rest = rest[:q]  
    slash = rest.find("/")  
    if slash == -1:  
        authority, path = rest, "/"  
    else:  
        authority, path = rest[:slash], rest[slash:]  
    if not path.startswith("/"):  
        path = "/" + path  
  
    # authority = [userinfo@]host[:port] ; last '@' wins per RFC 3986  
    at = authority.rfind("@")  
    if at != -1:  
        authority = authority[at + 1:]  
    port = DEFAULT_PORT  
    if authority.startswith("["):           # [::1] or [::1]:port  
        end = authority.find("]")  
        if end == -1:  
            return None  
        host = authority[:end + 1]  
        tail = authority[end + 1:]  
        if tail:  
            if not tail.startswith(":") or not tail[1:].isdigit():  
                return None  
            port = int(tail[1:])  
    else:  
        if ":" in authority:  
            host, _, pstr = authority.rpartition(":")  
            if not pstr.isdigit():  
                return None  
            port = int(pstr)  
        else:  
            host = authority  
    host = host.lower()  
    if not host:  
        return None  
  
    return {  
        "host": _idna(host),  
        "port": port,  
        "path": _quote_path(path),  
        "data": _unquote(query) if query else b"",  
    }  
  
  
def build_request_line(host, path, data_len):  
    """host SP path SP content-length CRLF — bare host, no port."""  
    return ("%s %s %d\r\n" % (host, path, data_len)).encode("ascii")  
  
  
async def _open_connection(host, port, timeout):  
    from mpos.net.async_dns import getaddrinfo_async  
  
    async def _connect():  
        # Warm the resolver off the event-loop thread (same trick as  
        # aiohttp) so a slow lookup doesn't stall the UI.  
        await getaddrinfo_async(host, port)  
        return await asyncio.open_connection(host, port)  
  
    if timeout is not None:  
        return await asyncio.wait_for(_connect(), timeout)  
    return await _connect()  
  
  
async def request(host, path="/", data=b"", port=DEFAULT_PORT,  
                  timeout=15, max_redirects=MAX_REDIRECTS,  
                  chunk_callback=None):  
    """One spartan request, following same-host '3' redirects.  
  
    Returns (status:int, meta:str, body:bytes|None).  
      status 2 -> meta is mimetype, body is the document (or None if  
                  chunk_callback consumed it)  
      status 3 -> handled internally; only surfaces if max_redirects hit  
      status 4/5 -> meta is the human-readable error message  
    """  
    redirects = 0  
    while True:  
        reader, writer = await _open_connection(host, port, timeout)  
        try:  
            writer.write(build_request_line(host, path, len(data)))  
            if data:  
                writer.write(data)  
            await writer.drain()  
  
            async def _read_status():  
                return await reader.readline()  
  
            if timeout is not None:  
                line = await asyncio.wait_for(_read_status(), timeout)  
            else:  
                line = await _read_status()  
            status_line = line.decode("ascii", "replace").rstrip("\r\n")  
            if len(status_line) < 1 or status_line[0] not in "2345":  
                raise ValueError("bad status line: %r" % status_line)  
            status = int(status_line[0])  
            meta = status_line[1:].strip()  
  
            if status == 3:  
                # Redirect: meta is an absolute path on THIS host.  
                if redirects >= max_redirects:  
                    return (status, meta, None)  
                if not meta.startswith("/"):  
                    return (4, "invalid redirect %r" % meta, None)  
                path = meta  
                redirects += 1  
                continue  
  
            if status != 2:  
                return (status, meta, None)  
  
            # Success: everything after CRLF is the body.  
            if chunk_callback is None:  
                body = await reader.read()  
                return (status, meta, body)  
            while True:  
                chunk = await reader.read(READ_CHUNK)  
                if not chunk:  
                    break  
                await chunk_callback(chunk)  
            return (status, meta, None)  
        finally:  
            try:  
                writer.close()  
                await writer.wait_closed()  
            except Exception:  
                pass  
  
  
async def fetch(url, **kwargs):  
    """request() convenience wrapper taking a spartan:// URL."""  
    parts = parse_url(url)  
    if parts is None:  
        return (4, "malformed spartan URL", None)  
    return await request(parts["host"], parts["path"], parts["data"],  
                         parts["port"], **kwargs)
