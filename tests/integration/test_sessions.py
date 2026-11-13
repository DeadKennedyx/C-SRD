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
from session_worker import events, serve, digest
from session_evidence import answer_candidate, Evidence
from summarize_sessions import paired, batch_metrics, matrix_application, application_timing, flat_cells, write_csv

TOOL=str(Path(sys.argv.pop(1)).resolve())


class Sessions(unittest.TestCase):
    def test_matrix_costs_reach_csv_and_missing_metrics_remain_unknown(self):
        original = {"status":"completed", "case":"case", "profile":"clang-O2", "variant":"original",
                    "binary_sha256":"a"*64, "binary_bytes":1000, "binary_size_ratio":1,
                    "timing":{"median_paired_ratio":1}}
        candidate = {**original, "variant":"candidate", "binary_sha256":"b"*64,
                     "binary_bytes":2000, "binary_size_ratio":2}
        app = matrix_application([original, candidate])
        key = ("case", "clang-O2", "candidate")
        app[key].update(application_timing({"median_paired_ratio":3, "cpu_median_paired_ratio":2.5,
            "cpu_median_seconds":0.25, "executable_peak_rss_median_bytes":4096, "peak_rss_median_bytes":65536}))
        sessions = [{"case":"case", "profile":"clang-O2", "variant":variant, "repetition":0,
                     "grades":{status:16}, "native_cpu_ns_per_request":cpu}
                    for variant,status,cpu in (("original","proved-under-model",10),("candidate","unsupported",20))]
        rows = flat_cells(paired(sessions,app))
        row = next(r for r in rows if r["variant"]=="candidate")
        self.assertEqual(row["application_runtime_ratio"],3)
        self.assertEqual(row["application_cpu_ratio"],2.5)
        self.assertEqual(row["application_executable_peak_rss_bytes"],4096)
        self.assertEqual(row["application_rusage_peak_rss_bytes"],65536)
        self.assertFalse(row["application_binary_bytes_identical_to_original"])
        self.assertIsNone(row["application_function_symbol_ratio"])
        self.assertIsNone(row["native_cpu_ns_per_request_paired_ratio_median"])
        self.assertEqual(row["native_cpu_ns_per_request_attempt_paired_ratio_median"],2)
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/"cells.csv";write_csv(path,rows)
            import csv
            with path.open() as handle: saved=list(csv.DictReader(handle))
            self.assertEqual(len(saved),2)
            self.assertTrue(all(r["application_function_symbol_ratio"]=="" for r in saved))

    def test_external_tool_bindings_preserve_absolute_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary).resolve()/"tool";path.write_bytes(b"external component")
            evidence=Evidence();evidence.bind(path)
            self.assertEqual(evidence.bindings,{str(path):digest(path.read_bytes())})
            path.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError,"bound evidence changed"):
                evidence.bind(path,next(iter(evidence.bindings.values())))

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
        self.assertEqual(candidate["metrics"]["native_cpu_ns_per_request"]["attempt_paired_ratios"]["n"],3)
        rows[-1]["grades"]={"unsupported":160}
        rows[-1]["native_cpu_ns_per_request"]=None
        candidate=next(r for r in paired(rows,app) if r["variant"]=="candidate")
        self.assertFalse(candidate["all_measured_requests_proved_under_model"])
        self.assertEqual(candidate["metrics"]["native_cpu_ns_per_request"]["absolute"]["n"],2)

    def test_unsupported_answers_are_explicit_and_not_candidates(self):
        answer={"candidate_sha256":None,"status":"unsupported","reason":"unsupported input"}
        self.assertIsNone(answer_candidate(answer,True))
        for value in ({**answer,"candidate_sha256":"a"*64},{**answer,"reason":""},
                      {**answer,"status":"reconstructed"},{"candidate_sha256":"bad"}):
            with self.assertRaises(ValueError):answer_candidate(value,True)
        with self.assertRaises(ValueError):answer_candidate(answer,False)
        self.assertEqual(answer_candidate({"candidate_sha256":"a"*64},False),"a"*64)
        native={"resources":{"cpu_ns":{"native":20,"jvm":10},"wall_ns":40},
                "result":{"requests":1,"decompile_ns":[12],"flush_ns":[2]}}
        adapter={"resources":{"cpu_ns":{"adapter":5},"wall_ns":10},
                 "result":{"requests":1,"reconstruct_ns":[5],"answers":[answer],"metrics":[{}]}}
        for phase,roles in ((native,("native","jvm")),(adapter,("adapter",))):
            for key in ("before_rss_bytes","after_rss_bytes","peak_sampled_rss_bytes"):
                phase["resources"][key]={role:1024 for role in roles}
        measured=batch_metrics(native,adapter)
        self.assertEqual(measured["combined_cpu_ns_per_request"],35)
        self.assertIsNone(measured["emitted_statements"])

    @unittest.skipUnless(sys.platform.startswith("linux"),"Linux persistent-adapter protocol")
    def test_adapter_continues_after_unsupported_request(self):
        export={"schema_version":1,"function":"kernel","arity":1,
                "nodes":[{"size":4,"parameter":0,"input":True},{"size":4,"constant":"0"}],
                "operations":[{"opcode":"RETURN","inputs":[1,0]}]}
        reconstruct(export)  # Validate the positive control before the protocol.
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/"exports").mkdir()
            ids=[]
            for value in (export,{**export,"schema_version":999}):
                encoded=json.dumps(value).encode();sha=digest(encoded);ids.append(sha)
                (root/"exports"/(sha+".json")).write_bytes(encoded)
            save(root/"jvm-phases.json",{"phases":[
                {"phase":"first","result":{"exports":[ids[0]]}},
                {"phase":"empty","result":{"exports":[]}},
                {"phase":"batch-0","result":{"exports":[ids[1],ids[0]]}}]})
            result=serve({"session_seconds":15,"retain_unsupported":True},root,"adapter",
                lambda p:[sys.executable,ROOT/"tools/session_worker.py","--adapter",p],
                [("first",True,1),("empty",True,0),("batch-0",True,2)])
            self.assertEqual(result["status"],"completed")
            answers=result["phases"][-1]["result"]["answers"]
            self.assertEqual([a["status"] for a in answers],["unsupported","reconstructed"])
            self.assertIsNone(answers[0]["candidate_sha256"])
            self.assertEqual(answers[1]["candidate_sha256"],result["phases"][0]["result"]["answers"][0]["candidate_sha256"])
            self.assertEqual(len(list((root/"answers").glob("*.c"))),1)

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
