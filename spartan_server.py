"""spartan:// server for MicroPythonOS.  
  
Serves a document root over TCP (default port 300) per the Spartan  
spec 2021-03-24:  
  
    request  = host SP path-absolute SP content-length CRLF [data-block]  
    reply    = '2' SP mimetype CRLF body  
             / '3' SP path-absolute CRLF  
             / '4' SP errormsg CRLF  
             / '5' SP errormsg CRLF  
  
Requests with a non-zero content-length are routed to an optional  
upload_handler(host, path, data) coroutine — use it for guestbooks,  
file uploads, etc. Everything runs on the TaskManager asyncio loop.  
  
No LVGL or hardware imports: desktop-testable.  
"""  
  
import asyncio  
import logging  
import os  
import stat  
  
logger = logging.getLogger(__name__)  
  
DEFAULT_PORT = 300  
MAX_REQUEST_LINE = 512       # spec doesn't bound it; keep a sane cap  
MAX_DATA_BLOCK = 64 * 1024   # refuse bigger uploads (RAM bound on ESP32)  
READ_TIMEOUT_S = 30          # idle-client cutoff  
  
_MIME = {  
    ".gmi":    "text/gemini",  
    ".gemini": "text/gemini",  
    ".txt":    "text/plain",  
    ".md":     "text/markdown",  
    ".html":   "text/html",  
    ".css":    "text/css",  
    ".csv":    "text/csv",  
    ".json":   "application/json",  
    ".png":    "image/png",  
    ".jpg":    "image/jpeg",  
    ".gif":    "image/gif",  
    ".mp3":    "audio/mpeg",  
    ".wav":    "audio/wav",  
}  
_DEFAULT_MIME = "application/octet-stream"  
  
  
def _mimetype(path):  
    dot = path.rfind(".")  
    if dot != -1:  
        ext = path[dot:].lower()  
        if ext in _MIME:  
            return _MIME[ext]  
    return _DEFAULT_MIME  
  
  
def _unquote_path(path):  
    """%-decode a request path for filesystem lookup."""  
    out = bytearray()  
    raw = path.encode("ascii", "replace")  
    i = 0  
    while i < len(raw):  
        if raw[i:i + 1] == b"%" and i + 2 < len(raw) + 1:  
            try:  
                out.append(int(raw[i + 1:i + 3], 16))  
                i += 3  
                continue  
            except (ValueError, IndexError):  
                pass  
        out.append(raw[i])  
        i += 1  
    return bytes(out).decode("utf-8", "replace")  
  
  
class SpartanServer:  
    """Listens for Spartan requests and serves files from a docroot.  
  
    Usage:  
        srv = SpartanServer("/sd/spartan", port=300)  
        TaskManager.create_task(srv.serve())  
    """  
  
    def __init__(self, docroot, port=DEFAULT_PORT, host="0.0.0.0",  
                 upload_handler=None, index_files=("index.gmi", "index.txt")):  
        self.docroot = docroot  
        self.port = port  
        self.host = host  
        self.upload_handler = upload_handler   # async fn(host, path, data) -> (status, meta, body|None)  
        self.index_files = index_files  
        self._server = None  
  
    async def serve(self):  
        """Coroutine: bind and serve until cancelled/stop()."""  
        self._server = await asyncio.start_server(  
            self._handle_client, self.host, self.port)  
        if __debug__:  
            logger.debug("spartan:// listening on %s:%d serving %s",  
                         self.host, self.port, self.docroot)  
        try:  
            await self._server.wait_closed()   # blocks; stop() closes it  
        except AttributeError:  
            # MicroPython's start_server may lack wait_closed: idle loop  
            while True:  
                await asyncio.sleep(3600)  
  
    def stop(self):  
        if self._server:  
            try:  
                self._server.close()  
            except Exception:  
                pass  
            self._server = None  
  
    # ----------------------------------------------------------  
    # Connection handling  
    # ----------------------------------------------------------  
  
    async def _handle_client(self, reader, writer):  
        try:  
            async def _readline():  
                return await reader.readline()  
  
            line = await asyncio.wait_for(_readline(), READ_TIMEOUT_S)  
            parsed = self._parse_request_line(line)  
            if parsed is None:  
                await self._reply(writer, 4, "Malformed request line")  
                return  
            host, path, length = parsed  
  
            if length > MAX_DATA_BLOCK:  
                await self._reply(writer, 4, "Data block too large")  
                return  
            data = b""  
            if length:  
                try:  
                    data = await asyncio.wait_for(  
                        reader.readexactly(length), READ_TIMEOUT_S)  
                except Exception:  
                    await self._reply(writer, 4, "Truncated data block")  
                    return  
  
            if __debug__:  
                logger.debug("spartan req: %s %s %d", host, path, length)  
  
            if length:  
                await self._serve_upload(writer, host, path, data)  
            else:  
                await self._serve_file(writer, path)  
        except asyncio.TimeoutError:  
            try:  
                await self._reply(writer, 4, "Request timed out")  
            except Exception:  
                pass  
        except Exception as e:  
            logger.error("spartan client error: %s", e)  
            try:  
                await self._reply(writer, 5, "Internal server error")  
            except Exception:  
                pass  
        finally:  
            try:  
                writer.close()  
                await writer.wait_closed()  
            except Exception:  
                pass  
  
    @staticmethod  
    def _parse_request_line(line):  
        """'host SP path SP length CRLF' -> (host, path, length)|None."""  
        try:  
            text = line.decode("ascii").rstrip("\r\n")  
        except Exception:  
            return None  
        if not text or len(text) > MAX_REQUEST_LINE:  
            return None  
        # Two separating spaces; host and path contain none.  
        sp1 = text.find(" ")  
        sp2 = text.rfind(" ")  
        if sp1 == -1 or sp1 == sp2:  
            return None  
        host = text[:sp1]  
        path = text[sp1 + 1:sp2]  
        length_s = text[sp2 + 1:]  
        if not host or not path.startswith("/") or not length_s.isdigit():  
            return None  
        return host, path, int(length_s)  
  
    async def _reply(self, writer, status, meta, body=b""):  
        writer.write(b"%d %s\r\n" % (status, meta.encode("utf-8")))  
        if body:  
            writer.write(body)  
        await writer.drain()  
  
    # ----------------------------------------------------------  
    # File serving  
    # ----------------------------------------------------------  
  
    def _resolve(self, path):  
        """Map request path into docroot, rejecting traversal."""  
        rel = _unquote_path(path)  
        # Normalize: strip leading '/', resolve '..' defensively.  
        parts = []  
        for seg in rel.split("/"):  
            if seg in ("", "."):  
                continue  
            if seg == "..":  
                if parts:  
                    parts.pop()  
                continue  
            parts.append(seg)  
        rel = "/".join(parts)  
        fspath = self.docroot.rstrip("/") + "/" + rel  
        if not fspath.startswith(self.docroot.rstrip("/") + "/"):  
            return None  
        return fspath, rel  
  
    async def _serve_file(self, writer, path):  
        resolved = self._resolve(path)  
        if resolved is None:  
            await self._reply(writer, 4, "Bad path")  
            return  
        fspath, rel = resolved  
        try:  
            st = os.stat(fspath)  
        except OSError:  
            await self._reply(writer, 4, 'File "%s" not found' % path)  
            return  
  
        if stat.S_ISDIR(st[0]):  
            # Directory: redirect to trailing slash, else serve index.  
            if not path.endswith("/"):  
                await self._reply(writer, 3, path + "/")  
                return  
            for index in self.index_files:  
                try:  
                    os.stat(fspath.rstrip("/") + "/" + index)  
                    fspath = fspath.rstrip("/") + "/" + index  
                    break  
                except OSError:  
                    continue  
            else:  
                await self._reply(writer, 4, "Directory has no index")  
                return  
            try:  
                st = os.stat(fspath)  
            except OSError:  
                await self._reply(writer, 4, 'File "%s" not found' % path)  
                return  
  
        mime = _mimetype(fspath)  
        writer.write(b"2 %s\r\n" % mime.encode("ascii"))  
        await writer.drain()  
        # Stream the body in chunks — never buffer whole files in RAM.  
        try:  
            f = open(fspath, "rb")  
            try:  
                while True:  
                    chunk = f.read(4096)  
                    if not chunk:  
                        break  
                    writer.write(chunk)  
                    await writer.drain()  
            finally:  
                f.close()  
        except OSError as e:  
            # Header already sent; nothing left to do but log.  
            logger.error("send body failed: %s", e)  
  
    async def _serve_upload(self, writer, host, path, data):  
        if self.upload_handler is None:  
            await self._reply(writer, 4, "This resource accepts no data")  
            return  
        try:  
            status, meta, body = await self.upload_handler(host, path, data)  
        except Exception as e:  
            logger.error("upload handler failed: %s", e)  
            status, meta, body = 5, "Upload handler error", None  
        await self._reply(writer, status, meta, body or b"")
