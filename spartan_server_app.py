"""Spartan server config app.  
  
Creates the served docroot inside this app's own data dir  
(data/<fullname>/spartan/) with a starter index.gmi, and starts/stops  
mpos.net.spartan_server.SpartanServer on the TaskManager loop.  
"""  
  
import os  
  
import lvgl as lv  
  
from mpos.app.activity import Activity  
from mpos.shared_preferences import SharedPreferences  
from mpos.task_manager import TaskManager  
from mpos.net.spartan_server import SpartanServer, DEFAULT_PORT  
  
APP_NAME = "com.micropythonos.spartanserver"  
DOCROOT = "data/%s/spartan" % APP_NAME   # per-app user data; removed on uninstall  
  
INDEX_GMI = """# My MicroPythonOS capsule 💪  
  
Hello from a Spartan server running on my badge!  
  
=>/files/ Browse files  
=:guestbook.txt Sign the guestbook  
"""  
  
GUESTBOOK_NOTE = """# Guestbook  
  
Uploads to =:guestbook.txt append lines here (see upload_handler).  
"""  
  
  
def _mkdirs(path):  
    """mkdir -p equivalent."""  
    parts = [p for p in path.split("/") if p]  
    cur = "" if path.startswith("/") else ""  
    for p in parts:  
        cur = cur + "/" + p if cur else p  
        try:  
            os.mkdir(cur)  
        except OSError:  
            pass  
  
  
class SpartanServerConfig(Activity):  
  
    def onCreate(self):  
        self.prefs = SharedPreferences(self.appFullName)  
        self._server = None  
  
        screen = lv.obj()  
        screen.set_flex_flow(lv.FLEX_FLOW.COLUMN)  
        screen.set_flex_align(lv.FLEX_ALIGN.START,  
                              lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)  
  
        title = lv.label(screen)  
        title.set_text("Spartan Server 💪")  
  
        # Port row  
        row = lv.obj(screen)  
        row.set_size(lv.pct(100), lv.SIZE_CONTENT)  
        row.set_flex_flow(lv.FLEX_FLOW.ROW)  
        pl = lv.label(row)  
        pl.set_text("Port:")  
        self.port_ta = lv.textarea(row)  
        self.port_ta.set_one_line(True)  
        self.port_ta.set_width(100)  
        self.port_ta.set_text(str(self.prefs.get_int("port", DEFAULT_PORT)))  
  
        # Buttons  
        setup_btn = lv.button(screen)  
        setup_btn.set_width(lv.pct(100))  
        lv.label(setup_btn).set_text("Create docroot + index.gmi")  
        setup_btn.add_event_cb(lambda e: self._setup_docroot(),  
                               lv.EVENT.CLICKED, None)  
  
        self.toggle_btn = lv.button(screen)  
        self.toggle_btn.set_width(lv.pct(100))  
        self.toggle_lbl = lv.label(self.toggle_btn)  
        self.toggle_lbl.set_text("Start server")  
        self.toggle_btn.add_event_cb(lambda e: self._toggle(),  
                                     lv.EVENT.CLICKED, None)  
  
        self.status = lv.label(screen)  
        self.status.set_width(lv.pct(100))  
        self.status.set_long_mode(lv.label.LONG_MODE.WRAP)  
        self._set_status("Docroot: /%s\nServer not running" % DOCROOT)  
  
        self.setContentView(screen)  
  
    # -------------------------------------------------------------  
  
    def _set_status(self, text):  
        self.status.set_text(text)  
  
    def _setup_docroot(self):  
        try:  
            _mkdirs(DOCROOT)  
            _mkdirs(DOCROOT + "/files")  
            for name, content in (("index.gmi", INDEX_GMI),  
                                  ("guestbook.txt", GUESTBOOK_NOTE)):  
                try:  
                    os.stat("%s/%s" % (DOCROOT, name))   # don't overwrite  
                except OSError:  
                    with open("%s/%s" % (DOCROOT, name), "w") as f:  
                        f.write(content)  
            self._set_status("Docroot ready: /%s" % DOCROOT)  
        except OSError as e:  
            self._set_status("Docroot setup failed: %s" % e)  
  
    def _toggle(self):  
        if self._server is None:  
            try:  
                port = int(self.port_ta.get_text() or DEFAULT_PORT)  
            except ValueError:  
                self._set_status("Bad port")  
                return  
            self.prefs.put_int("port", port)  
            self._setup_docroot()   # ensure docroot exists  
            self._server = SpartanServer(  
                DOCROOT, port=port, upload_handler=self._upload)  
            TaskManager.create_task(self._server.serve())  
            self.toggle_lbl.set_text("Stop server")  
            self._set_status("Serving /%s on spartan://<device-ip>:%d/"  
                             % (DOCROOT, port))  
        else:  
            self._server.stop()  
            self._server = None  
            self.toggle_lbl.set_text("Start server")  
            self._set_status("Server stopped")  
  
    async def _upload(self, host, path, data):  
        """Append '=:' uploads to files in the docroot (guestbook etc.)."""  
        rel = path.lstrip("/")  
        if ".." in rel.split("/"):  
            return (4, "Bad path", None)  
        try:  
            with open("%s/%s" % (DOCROOT, rel), "ab") as f:  
                f.write(data.replace(b"\r\n", b"\n").rstrip(b"\n") + b"\n")  
            return (2, "text/plain", b"Stored!\n")  
        except OSError as e:  
            return (4, "Upload failed: %s" % e, None)  
  
    def onDestroy(self):  
        if self._server:  
            self._server.stop()  
            self._server = None
