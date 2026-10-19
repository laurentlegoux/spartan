"""Spartan protocol browser activity.  
  
Renders text/gemini served over spartan:// (TCP 300). '=>' lines become  
tappable links; '=:' lines open an input dialog whose text is sent as  
the request data-block.  
"""  
  
import lvgl as lv  
  
from mpos.app.activity import Activity  
from mpos.task_manager import TaskManager  
from mpos.net import spartan  
  
HOME_URL = "spartan://spartan.mozz.us/"  
  
  
def resolve_link(base_url, link):  
    """Resolve a gemtext link target against the current spartan URL.  
  
    Returns an absolute spartan:// URL, or the raw link if it carries  
    its own scheme (so http(s)/gemini links can be handed to deeplink).  
    """  
    if "://" in link:  
        return link  
    base = spartan.parse_url(base_url)  
    if base is None:  
        return link  
    host = base["host"]  
    port = base["port"]  
    origin = "spartan://%s%s" % (host, "" if port == spartan.DEFAULT_PORT  
                                 else ":%d" % port)  
    if link.startswith("/"):  
        return origin + link  
    # Relative: merge against the base directory.  
    base_path = base["path"]  
    if not base_path.endswith("/"):  
        base_path = base_path.rsplit("/", 1)[0] + "/"  
    merged = base_path + link  
    parts = []  
    for p in merged.split("/"):  
        if p in ("", "."):  
            continue  
        if p == "..":  
            if parts:  
                parts.pop()  
            continue  
        parts.append(p)  
    return origin + "/" + "/".join(parts)  
  
  
class SpartanBrowser(Activity):  
  
    def onCreate(self):  
        screen = lv.obj()  
        screen.set_flex_flow(lv.FLEX_FLOW.COLUMN)  
        screen.set_flex_align(lv.FLEX_ALIGN.START,  
                              lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)  
  
        # Navigation bar: [Back] [address textarea] [Go]  
        bar = lv.obj(screen)  
        bar.set_size(lv.pct(100), lv.SIZE_CONTENT)  
        bar.set_flex_flow(lv.FLEX_FLOW.ROW)  
        bar.set_flex_align(lv.FLEX_ALIGN.CENTER,  
                           lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)  
  
        back = lv.button(bar)  
        back.add_event_cb(lambda e: self._back(), lv.EVENT.CLICKED, None)  
        lv.label(back).set_text(lv.SYMBOL.LEFT)  
  
        self.addr = lv.textarea(bar)  
        self.addr.set_one_line(True)  
        self.addr.set_flex_grow(1)  
        self.addr.set_placeholder_text("spartan://host/path")  
        self.addr.add_event_cb(lambda e: self._navigate(self.addr.get_text()),  
                               lv.EVENT.READY, None)  # Enter key  
  
        go = lv.button(bar)  
        go.add_event_cb(lambda e: self._navigate(self.addr.get_text()),  
                        lv.EVENT.CLICKED, None)  
        lv.label(go).set_text(lv.SYMBOL.RIGHT)  
  
        # Status line  
        self.status = lv.label(screen)  
        self.status.set_text("")  
        self.status.set_width(lv.pct(100))  
  
        # Scrollable document area  
        self.content = lv.obj(screen)  
        self.content.set_size(lv.pct(100), lv.pct(100))  
        self.content.set_flex_grow(1)  
        self.content.set_flex_flow(lv.FLEX_FLOW.COLUMN)  
        self.content.set_flex_align(lv.FLEX_ALIGN.START,  
                                    lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.START)  
        self.content.set_scrollbar_mode(lv.SCROLLBAR_MODE.AUTO)  
  
        self.history = []  
        self.setContentView(screen)  
  
    def onResume(self, screen):  
        if not self.history:  
            intent = self.getIntent()  
            url = intent.data if intent and intent.data else HOME_URL  
            self._navigate(url)  
  
    # --------------------------------------------------------------  
    # Navigation  
    # --------------------------------------------------------------  
  
    def _navigate(self, url, data=b""):  
        url = (url or "").strip()  
        if not url:  
            return  
        if not url.startswith("spartan://"):  
            # Non-spartan scheme or bare host: try adding scheme, else  
            # hand off to the system deeplink dispatcher.  
            if "://" not in url:  
                url = "spartan://" + url  
            else:  
                from mpos.content import deeplink  
                deeplink.open_url(url)  
                return  
        parts = spartan.parse_url(url)  
        if parts is None:  
            self._set_status("Malformed URL")  
            return  
        self._set_status("Connecting to %s:%d ..." % (parts["host"], parts["port"]))  
        TaskManager.create_task(self._load(url, parts, data))  
  
    def _back(self):  
        if len(self.history) > 1:  
            self.history.pop()          # current page  
            self._navigate(self.history.pop())  # previous page  
  
    async def _load(self, url, parts, data):  
        try:  
            status, meta, body = await spartan.request(  
                parts["host"], parts["path"],  
                data or parts["data"], parts["port"])  
        except Exception as e:  
            self.update_ui_threadsafe_if_foreground(  
                self._set_status, "Error: %s" % e)  
            return  
        self.update_ui_threadsafe_if_foreground(  
            self._render, url, status, meta, body)  
  
    # --------------------------------------------------------------  
    # Rendering  
    # --------------------------------------------------------------  
  
    def _render(self, url, status, meta, body):  
        self.addr.set_text(url)  
        self.content.clean()  
        self.content.scroll_to_y(0, lv.ANIM.OFF)  
        if status != 2:  
            self._set_status("Status %d: %s" % (status, meta))  
            return  
        self.history.append(url)  
        mimetype = meta.split(";")[0].strip().lower()  
        if mimetype in ("text/gemini", ""):  
            self._set_status("")  
            self._render_gemtext(url, (body or b"").decode("utf-8", "replace"))  
        elif mimetype.startswith("text/"):  
            self._set_status(meta)  
            self._add_text((body or b"").decode("utf-8", "replace"))  
        else:  
            self._set_status("%s — %d bytes (binary body not displayed)"  
                             % (meta, len(body or b"")))  
  
    def _render_gemtext(self, base_url, text):  
        pre = False  
        for raw in text.split("\n"):  
            line = raw.rstrip("\r")  
            if line.startswith("```"):  
                pre = not pre  
                continue  
            if pre:  
                self._add_text(line)  
            elif line.startswith("=:"):  
                target, name = self._split_link(line[2:])  
                self._add_prompt(base_url, target, name)  
            elif line.startswith("=>"):  
                target, name = self._split_link(line[2:])  
                self._add_link(base_url, target, name)  
            elif line.startswith("###"):  
                self._add_heading(line[3:].strip(), 3)  
            elif line.startswith("##"):  
                self._add_heading(line[2:].strip(), 2)  
            elif line.startswith("#"):  
                self._add_heading(line[1:].strip(), 1)  
            elif line.startswith("*"):  
                self._add_text("  • " + line[1:].strip())  
            elif line.startswith(">"):  
                self._add_text("  ❜ " + line[1:].strip())  
            else:  
                self._add_text(line)  
  
    @staticmethod  
    def _split_link(rest):  
        rest = rest.strip()  
        if not rest:  
            return "", ""  
        parts = rest.split(None, 1)  # split on first whitespace run  
        target = parts[0]  
        name = parts[1].strip() if len(parts) > 1 else target  
        return target, name  
  
    def _add_text(self, text):  
        lbl = lv.label(self.content)  
        lbl.set_text(text)  
        lbl.set_width(lv.pct(100))  
        lbl.set_long_mode(lv.label.LONG_MODE.WRAP)  
  
    def _add_heading(self, text, level):  
        lbl = lv.label(self.content)  
        # Reuse text with markers; real styling (fonts) can be added later.  
        lbl.set_text(("#" * level) + " " + text)  
        lbl.set_width(lv.pct(100))  
        lbl.set_long_mode(lv.label.LONG_MODE.WRAP)  
  
    def _add_link(self, base_url, target, name):  
        btn = lv.button(self.content)  
        btn.set_width(lv.pct(100))  
        lbl = lv.label(btn)  
        lbl.set_text("→ " + name)  
        lbl.set_long_mode(lv.label.LONG_MODE.WRAP)  
        url = resolve_link(base_url, target)  
        btn.add_event_cb(lambda e, u=url: self._navigate(u),  
                         lv.EVENT.CLICKED, None)  
  
    def _add_prompt(self, base_url, target, name):  
        btn = lv.button(self.content)  
        btn.set_width(lv.pct(100))  
        lbl = lv.label(btn)  
        lbl.set_text("✎ " + name)  
        lbl.set_long_mode(lv.label.LONG_MODE.WRAP)  
        url = resolve_link(base_url, target)  
        btn.add_event_cb(lambda e, u=url, n=name: self._prompt_input(u, n),  
                         lv.EVENT.CLICKED, None)  
  
    # --------------------------------------------------------------  
    # '=:' input prompt dialog  
    # --------------------------------------------------------------  
  
    def _prompt_input(self, url, name):  
        mbox = lv.msgbox(self.getScreen(), "Input", name, [], False)  
        ta = lv.textarea(mbox.get_content())  
        ta.set_width(lv.pct(100))  
        ta.set_height(80)  
        ta.set_placeholder_text("Text to upload...")  
        mbox.add_close_button()  
        send = mbox.add_footer_button("Send")  
        send.add_event_cb(  
            lambda e: (self._navigate(url, ta.get_text().encode("utf-8")),  
                       mbox.close()),  
            lv.EVENT.CLICKED, None)  
        mbox.center()  
  
    # --------------------------------------------------------------  
  
    def _set_status(self, text):  
        self.status.set_text(text)
