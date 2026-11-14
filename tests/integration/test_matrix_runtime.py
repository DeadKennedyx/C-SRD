"""Independent runtime labels, frozen selection, evidence corruption and live GDB."""
import copy
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))
from benchmark_oracles import ORACLES, MASK
from check_matrix_runtime import check
from fit_matrix_runtime import fit
from matrix_runtime_tasks import ARITIES, targets, vectors
from measure_matrix_runtime import grade, paired_summary

TOOL=str(Path(sys.argv.pop(1)).resolve())


class MatrixRuntime(unittest.TestCase):
    def test_task_labels_partition_and_independent_returns(self):
        for case in ARITIES:
            train,test=vectors(case,42)
            self.assertFalse(set(train)&set(test))
            self.assertEqual((train,test),vectors(case,42))
            self.assertNotEqual(test,vectors(case,43)[1])
            for vector in train+test:
                result=targets(case,vector)
                self.assertEqual(result["public_return"],ORACLES[case](*vector))
                if case=="morton16":
                    self.assertEqual(result["public_return"],result["intermediates"]["spread_x"] | (result["intermediates"]["spread_y"]<<1))
                if case=="rgb_luma8":
                    self.assertEqual(result["public_return"],result["intermediates"]["weighted_sum"]//256)
                if case=="crc32_byte":
                    value=result["intermediates"]["crc_after_four_rounds"]
                    for _ in range(4): value=(value>>1)^(0xedb88320 if value&1 else 0)
                    self.assertEqual(value^MASK,result["public_return"])
            for name in targets(case,train[0])["intermediates"]:
                self.assertGreater(len({targets(case,v)["intermediates"][name] for v in train}),1)
        self.assertEqual(targets("rgb_luma8",[0x010203])["intermediates"],{"red_component":1,"weighted_sum":464})

    def test_first_candidate_is_not_chosen_using_heldout_answers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); entries=[]
            labels=[0,1,7,31,255,0xffffffff,0x12345678,0xaabbccdd,12,29,888,0x80000000]
            for index,value in enumerate(labels):
                is_train=index<8
                samples=[{"offset":offset,"visit":0,"values":{"reg:x0":(3*value+7+(0 if is_train or offset==9 else 1))&MASK}}
                         for offset in (1,9)]
                trace={"status":"completed","samples":samples,"steps":2,"stack_read_failures":0,"vector_read_failures":0}
                path=root/f"{index}.json.gz"
                with gzip.open(path,"wt") as stream:json.dump(trace,stream)
                entries.append({"path":str(path),"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"split":"training" if is_train else "heldout"})
            config={"traces":entries[:8],"labels":{"value":labels[:8]}}
            answer=fit(config)
            result=grade(answer,entries[8:],{"value":labels[8:]})["value"]
            self.assertEqual(result["primary"]["status"],"wrong-candidate")
            self.assertEqual(result["primary"]["diagnostic_all_candidates"]["validated_models"],1)
            self.assertEqual(result["negative_control"]["status"],"no-candidate")
            bad=copy.deepcopy(answer);bad["targets"]["value"]["selected"]=bad["targets"]["value"]["models"][1]
            with self.assertRaisesRegex(ValueError,"first candidate"):grade(bad,entries[8:],{"value":labels[8:]})
            with self.assertRaisesRegex(ValueError,"count mismatch"):grade(answer,entries[8:],{"value":[0]})
            with self.assertRaisesRegex(ValueError,"held-out"):fit({"traces":entries,"labels":{"value":labels}})
            Path(entries[0]["path"]).write_bytes(b"changed trace")
            with self.assertRaisesRegex(ValueError,"digest"):fit(config)

    def test_unmeasured_recovery_is_not_zero_cost(self):
        group={"case":"rgb_luma8","profile":"clang-O2","variant":"original","repetition":0,
               "status":"incomplete-observation","traces":[{"split":"training","steps":1,
                   "resources":{"cpu_seconds":1.0,"wall_seconds":2.0,"peak_process_rss_bytes":100,"peak_sampled_tree_rss_bytes":110}}]}
        row=paired_summary([group])[0]
        self.assertIsNone(row["instruction_step_ratio"])
        self.assertIsNone(row["resource_phases"]["primary_observer"]["cpu_seconds"])
        self.assertTrue(all(t["status"]=="unassessed" and t["matched_recovery_cpu_ratio"] is None for t in row["targets"].values()))

    @unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("gdb"),"live Linux GDB required")
    def test_live_runtime_and_evidence_corruption(self):
        clang=shutil.which("clang-18") or shutil.which("clang")
        objdump=shutil.which("llvm-objdump-18") or shutil.which("llvm-objdump")
        self.assertTrue(clang and objdump)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            def execute(command,expected=0):
                result=subprocess.run(list(map(str,command)),capture_output=True,text=True,timeout=120)
                self.assertEqual(result.returncode,expected,result.stdout+result.stderr)
            matrix=root/"matrix"
            execute([sys.executable,ROOT/"tools/run_matrix.py","--matrix",ROOT/"benchmarks/rich.json","--csrd",TOOL,
                "--case","rgb_luma8","--profile","clang-O0","--profile","clang-O2","--compiler","clang="+clang,"--objdump",objdump,
                "--strategies","identity","--region-recipes","outline","--binary-copy-control","--no-select",
                "--inputs","8","--iterations","10000","--repetitions","3","--output-dir",matrix])
            built=json.loads((matrix/"matrix.json").read_text())
            binary=next(r["binary"] for r in built["records"] if r["variant"]=="original")
            probe=root/"probe.input";probe.write_text("0\n")
            # Validate nonzero SIMD lane bytes against a controlled register
            # write in a disposable process, not just the existence of fields.
            script=("python arch=gdb.selected_frame().architecture().name(); "
                    "reg='v0' if 'aarch64' in arch else 'xmm0'; "
                    "lane='v0.s.u[0]' if 'aarch64' in arch else 'xmm0.v4_int32[0]'; "
                    "gdb.execute('set $'+lane+' = 305419896'); "
                    "raw=bytes(gdb.parse_and_eval('$'+reg).bytes); "
                    "assert len(raw)==16 and int.from_bytes(raw[:4],'little')==305419896; print('SIMD_PROBE_OK')")
            inspected=subprocess.run(["gdb","--nx","--batch","-iex","set auto-load off","-ex","break *kernel",
                                      "-ex","run < "+str(probe),"-ex",script,"--args",binary],capture_output=True,text=True,timeout=20)
            self.assertEqual(inspected.returncode,0,inspected.stderr)
            self.assertIn("SIMD_PROBE_OK",inspected.stdout)
            command=[sys.executable,ROOT/"tools/measure_matrix_runtime.py","--matrix-report",matrix/"matrix.json",
                     "--case","rgb_luma8","--profile","clang-O0","--profile","clang-O2","--variant","original","--training","8","--heldout","8","--fit-repetitions","2"]
            output=root/"runtime"
            execute([*command,"--variant","outline-42","--variant","original-copy","--output-dir",output])
            report,evidence=check(output/"runtime.json")
            self.assertEqual(report["status"],"completed")
            self.assertEqual(len(report["groups"]),6)
            self.assertTrue(evidence.bindings)
            for group in report["groups"]:
                self.assertEqual(group["targets"]["public_return_control"]["primary"]["status"],"recovered-on-heldout")
                self.assertTrue(all(t["return_validated"] and not t["vector_read_failures"] for t in group["traces"]))
                with gzip.open(group["traces"][0]["path"],"rt") as stream:trace=json.load(stream)
                self.assertTrue(any(k.startswith("simd:") for k in trace["samples"][0]["values"]))
                if group["profile"]=="clang-O0" and group["variant"]=="outline-42":
                    self.assertTrue(any(sample["code_scope"]=="callee-or-other" for sample in trace["samples"]))
            original=(output/"runtime.json").read_bytes()
            altered=copy.deepcopy(report);altered["pairs"][0]["queries"]["training"]+=1
            (output/"runtime.json").write_text(json.dumps(altered))
            with self.assertRaisesRegex(ValueError,"summary changed"):check(output/"runtime.json")
            (output/"runtime.json").write_bytes(original)
            altered=copy.deepcopy(report);altered["groups"].append(altered["groups"][0])
            (output/"runtime.json").write_text(json.dumps(altered))
            with self.assertRaisesRegex(ValueError,"duplicate runtime group"):check(output/"runtime.json")
            (output/"runtime.json").write_bytes(original)
            group_path=Path(report["groups"][0]["directory"])/"group.json"
            group_bytes=group_path.read_bytes()
            altered=copy.deepcopy(report);altered["groups"][0]["traces"][0]["resources"]["cpu_seconds"]+=1
            group_path.write_text(json.dumps(altered["groups"][0]));(output/"runtime.json").write_text(json.dumps(altered))
            with self.assertRaisesRegex(ValueError,"resource counters"):check(output/"runtime.json")
            group_path.write_bytes(group_bytes);(output/"runtime.json").write_bytes(original)
            fit_config=Path(report["groups"][0]["directory"])/"fit-config.json"
            config=json.loads(fit_config.read_text());config["labels"]["weighted_sum"][0]^=1
            fit_config.write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError,"training partition or labels"):check(output/"runtime.json")
            limited=root/"limited"
            execute([*command,"--step-limit","1","--output-dir",limited],expected=1)
            incomplete,_=check(limited/"runtime.json")
            self.assertEqual(incomplete["status"],"completed-with-gaps")
            self.assertTrue(all(t["status"]=="unassessed" for t in incomplete["pairs"][0]["targets"].values()))


if __name__=="__main__":unittest.main()
