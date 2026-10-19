"""Round-trip test: SpartanServer <-> spartan.request."""  
  
import _thread  
import os  
import sys  
import time  
import unittest  
  
sys.path.insert(0, "../internal_filesystem/lib")  
  
from mpos import TaskManager  
from mpos.net import spartan  
from mpos.net.spartan_server import SpartanServer  
  
DOCROOT = "/tmp/spartan_docroot"  
PORT = 13000  
  
  
class TestSpartanServer(unittest.TestCase):  
  
    @classmethod  
    def setUpClass(cls):  
        try:  
            os.mkdir(DOCROOT)  
        except OSError:  
            pass  
        with open(DOCROOT + "/index.gmi", "w") as f:  
            f.write("# Hello Spartan\n=>/about.txt About\n")  
        with open(DOCROOT + "/about.txt", "w") as f:  
            f.write("plain text body")  
  
        TaskManager.enable()  
        _thread.stack_size(TaskManager.good_stack_size())  
        _thread.start_new_thread(TaskManager.start, ())  
        deadline = time.time() + 5  
        while TaskManager.keep_running is not True and time.time() < deadline:  
            time.sleep(0.05)  
  
    @classmethod  
    def tearDownClass(cls):  
        TaskManager.stop()  
  
    def _roundtrip(self, coro):  
        """Run coro on the TaskManager loop, collecting its result."""  
        state = {"done": False, "result": None, "error": None}  
  
        async def _wrap():  
            try:  
                state["result"] = await coro()  
            except Exception as e:  
                state["error"] = e  
            finally:  
                state["done"] = True  
  
        TaskManager.create_task(_wrap())  
        deadline = time.time() + 15  
        while not state["done"] and time.time() < deadline:  
            time.sleep(0.05)  
        self.assertTrue(state["done"], "timed out")  
        if state["error"]:  
            raise state["error"]  
        return state["result"]  
  
    def test_serves_index(self):  
        async def go():  
            srv = SpartanServer(DOCROOT, port=PORT)  
            TaskManager.create_task(srv.serve())  
            await TaskManager.sleep_ms(300)  
            res = await spartan.request("127.0.0.1", "/", port=PORT)  
            srv.stop()  
            return res  
  
        status, meta, body = self._roundtrip(go)  
        self.assertEqual(status, 2)  
        self.assertTrue(meta.startswith("text/gemini"))  
        self.assertIn(b"Hello Spartan", body)  
  
    def test_file_and_404(self):  
        async def go():  
            srv = SpartanServer(DOCROOT, port=PORT + 1)  
            TaskManager.create_task(srv.serve())  
            await TaskManager.sleep_ms(300)  
            ok = await spartan.request("127.0.0.1", "/about.txt",  
                                       port=PORT + 1)  
            missing = await spartan.request("127.0.0.1", "/nope.txt",  
                                            port=PORT + 1)  
            srv.stop()  
            return ok, missing  
  
        (s1, m1, b1), (s2, m2, b2) = self._roundtrip(go)  
        self.assertEqual(s1, 2)  
        self.assertEqual(m1, "text/plain")  
        self.assertEqual(b1, b"plain text body")  
        self.assertEqual(s2, 4)  
  
    def test_upload(self):  
        async def handler(host, path, data):  
            return 2, "text/plain", b"echo:" + data  
  
        async def go():  
            srv = SpartanServer(DOCROOT, port=PORT + 2,  
                                upload_handler=handler)  
            TaskManager.create_task(srv.serve())  
            await TaskManager.sleep_ms(300)  
            res = await spartan.request("127.0.0.1", "/submit",  
                                        data=b"hello world",  
                                        port=PORT + 2)  
            srv.stop()  
            return res  
  
        status, meta, body = self._roundtrip(go)  
        self.assertEqual(status, 2)  
        self.assertEqual(body, b"echo:hello world")  
  
    def test_malformed_request(self):  
        async def go():  
            srv = SpartanServer(DOCROOT, port=PORT + 3)  
            TaskManager.create_task(srv.serve())  
            await TaskManager.sleep_ms(300)  
            import asyncio  
            reader, writer = await asyncio.open_connection(  
                "127.0.0.1", PORT + 3)  
            writer.write(b"this is not a valid line\r\n")  
            await writer.drain()  
            line = await reader.readline()  
            writer.close()  
            srv.stop()  
            return line  
  
        line = self._roundtrip(go)  
        self.assertTrue(line.startswith(b"4 "))  
  
  
if __name__ == "__main__":  
    unittest.main()
