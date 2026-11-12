"""Counter controls, frozen-export correspondence and optional live sessions."""
import copy
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))
from process_counters import Phase, difference
from effort_resources import measure, save
from pcode_reconstruct import reconstruct
from session_worker import events
from summarize_sessions import paired

TOOL=str(Path(sys.argv.pop(1)).resolve())


class Sessions(unittest.TestCase):
    def test_export_semantics_frozen(self):
        def block(path):
            text=path.read_text()
            return text.split('            HighFunction high = result.getHighFunction();\n',1)[1].split('            report.addProperty("status", "decompiled");',1)[0]
        self.assertEqual(block(ROOT/"tools/ghidra/ExportCSRD.java"),block(ROOT/"tools/ghidra/SessionCSRD.java"))

    def test_lost_and_reset_counters_are_not_zero_cost(self):
        before={"1:100":{"cpu_ns":100,"role":"native","executable":"/decompile"}}
        for after in ({},{"1:101":{"cpu_ns":1,"role":"native","executable":"/decompile"}},
                      {"1:100":{"cpu_ns":99,"role":"native","executable":"/decompile"}},
                      {"1:100":{"cpu_ns":110,"role":"native","executable":"/another"}}):
            with self.assertRaises(ValueError):difference(before,after)
        after=copy.deepcopy(before);after["1:100"]["cpu_ns"]=125
        self.assertEqual(difference(before,after),{"native":25})

    def test_paired_costs_count_sessions_and_preserve_unknowns(self):
        rows=[]
        for repetition in range(3):
            for variant in ("original","candidate"):
                rows.append({"case":"fixture","profile":"compiler","variant":variant,"repetition":repetition,
                             "grades":{"proved-under-model":160},"batches":5,
                             "native_cpu_ns_per_request":10 if variant=="original" else 20*(repetition+1)})
        app={("fixture","compiler",v):{} for v in ("original","candidate")}
        candidate=next(r for r in paired(rows,app) if r["variant"]=="candidate")
        self.assertEqual(candidate["sessions"],3)
        ratios=candidate["metrics"]["native_cpu_ns_per_request"]["paired_ratios"]
        self.assertEqual(ratios,{"n":3,"median":4.0,"min":2.0,"max":6.0})
        rows[-1]["grades"]={"inconclusive":160}
        candidate=next(r for r in paired(rows,app) if r["variant"]=="candidate")
        self.assertEqual(candidate["sessions"],3)
        self.assertFalse(candidate["all_measured_requests_proved_under_model"])
        self.assertEqual(candidate["metrics"]["native_cpu_ns_per_request"]["absolute"]["n"],3)
        self.assertEqual(candidate["metrics"]["native_cpu_ns_per_request"]["paired_ratios"]["n"],2)

    @unittest.skipUnless(sys.platform.startswith("linux"),"Linux process CPU clock/RSS controls")
    def test_cpu_sleep_memory_and_disappearance(self):
        source="""import sys,time
held=None
for line in sys.stdin:
 if line.strip()=='burn':
  end=time.process_time()+.12
  while time.process_time()<end: pass
 elif line.strip()=='sleep':time.sleep(.15)
 elif line.strip()=='memory':held=bytearray(32*1024*1024)
 print('ok',flush=True)
"""
        child=subprocess.Popen([sys.executable,"-u","-c",source],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        try:
            child.stdin.write("sleep\n");child.stdin.flush();self.assertEqual(child.stdout.readline(),"ok\n")
            for command in ("burn","sleep","memory"):
                phase=Phase(child.pid,"adapter",interval=.002)
                child.stdin.write(command+"\n");child.stdin.flush();self.assertEqual(child.stdout.readline(),"ok\n")
                result=phase.finish();self.assertEqual(result["status"],"completed",result)
                cpu=result["cpu_ns"]["adapter"]/1e9
                if command=="burn":self.assertGreater(cpu,.10);self.assertLess(cpu,.5)
                elif command=="sleep":self.assertLess(cpu,.06);self.assertGreater(result["wall_ns"]/1e9,.14)
                else:self.assertGreater(result["after_rss_bytes"]["adapter"]-result["before_rss_bytes"]["adapter"],28*1024*1024)
            phase=Phase(child.pid,"adapter");child.terminate();child.wait()
            self.assertEqual(phase.finish()["status"],"invalid-counters")
        finally:
            if child.poll() is None:child.terminate();child.wait()
            child.stdin.close();child.stdout.close()

    @unittest.skipUnless(sys.platform.startswith("linux"),"Linux owned-peer protocol controls")
    def test_protocol_rejects_reordered_phases_and_false_request_counts(self):
        source="""import json,os,socket,sys
with socket.create_connection(('127.0.0.1',int(sys.argv[1]))) as c,c.makefile('rwb',buffering=0) as s:
 def send(v):
  s.write((json.dumps(v)+'\\n').encode());return s.readline()
 send({'event':'hello','payload':{'token':'test','role':'adapter','pid':os.getpid()}})
 name='wrong' if sys.argv[2]=='reordered' else 'batch-0'
 if send({'event':'begin','phase':name,'stable':True})==b'ok\\n':
  send({'event':'end','phase':name,'stable':True,'payload':{'requests':0}})
"""
        with tempfile.TemporaryDirectory() as tmp:
            for mode in ("reordered","false-count"):
                with socket.socket() as server:
                    server.bind(("127.0.0.1",0));server.listen(1)
                    child=subprocess.Popen([sys.executable,"-c",source,str(server.getsockname()[1]),mode],
                                           stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                    try:
                        with self.assertRaisesRegex(ValueError,"reordered phase|count mismatch"):
                            events(server,"test","adapter",child,Path(tmp)/"phase.json",time.monotonic()+5,
                                   [("batch-0",True,1)])
                        child.communicate(timeout=5)
                    finally:
                        if child.poll() is None:child.kill();child.communicate()

    @unittest.skipUnless(sys.platform.startswith("linux") and os.environ.get("CSRD_GHIDRA_HEADLESS"),"live Linux Ghidra session not configured")
    def test_live_session_matches_cold_export_and_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/"original.c"
            source.write_text("unsigned int kernel(unsigned int x,unsigned int y){return 3u*(x+y)+11u;}\n")
            harness=root/"main.c";harness.write_text("int main(void){return 0;}\n")
            compiler=shutil.which("clang-18") or shutil.which("clang")
            subprocess.run([compiler,"-O2",source,harness,"-o",root/"program"],check=True)
            output=root/"session";output.mkdir()
            config={"binary":str(root/"program"),"function":"kernel","arity":2,"headless":os.environ["CSRD_GHIDRA_HEADLESS"],
                    "analysis_seconds":30,"decompile_seconds":15,"session_seconds":90,"warmup_calls":2,"calls":2,"batches":2}
            save(output/"config.json",config)
            resources=measure([sys.executable,ROOT/"tools/session_worker.py",output/"config.json"],root/"resources",wall_seconds=100)
            self.assertEqual(resources["status"],"completed",(root/"resources/stderr.txt").read_text())
            session=json.loads((output/"session.json").read_text());self.assertEqual(session["status"],"completed")
            cold=root/"cold";cold.mkdir();project=root/"project";project.mkdir()
            subprocess.run([config["headless"],project,"cold","-import",root/"program","-deleteProject","-max-cpu","2",
                            "-scriptPath",ROOT/"tools/ghidra","-postScript","ExportCSRD.java","kernel","2","15",cold],
                           check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=60)
            expected=reconstruct(json.loads((cold/"export.json").read_text()))
            answers=list((output/"answers").glob("*.c"));self.assertTrue(answers)
            for path in answers:
                self.assertEqual(path.read_text(),expected)
                result=subprocess.run([TOOL,"verify",source,path],capture_output=True)
                self.assertEqual(result.returncode,0,result.stderr)
            for role in ("jvm","adapter"):
                phases=session[role]["phases"]
                self.assertEqual(len([p for p in phases if p["phase"].startswith("batch-")]),2)
                empty=next(p for p in phases if p["phase"]=="empty")
                self.assertEqual(empty["result"]["requests"],0)
                if role=="jvm":self.assertLess(empty["resources"]["cpu_ns"]["native"],20_000_000)
                for phase in phases:
                    self.assertEqual(phase["resources"]["status"],"completed")


if __name__=="__main__":unittest.main()
