import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT / "tests/differential"))
from run import compilers, execute
TOOL=str(Path(sys.argv.pop(1)).resolve())
SOURCE=ROOT / "tests/fixtures/control_regions.c"
NAMES=["flow_mix","flow_scopes","flow_recursive","flow_buffer","flow_heap","flow_floating","flow_stream","flow_line"]


class ControlRegions(unittest.TestCase):
    def transform(self,source,destination,scope,seed=42):
        report=destination.with_suffix(".json")
        execute([TOOL,"transform",source,"-o",destination,"--scope",scope,"--seed",str(seed),"--report",report])
        return json.loads(report.read_text())

    def test_effects_control_and_combinations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            control=root / "control.c"
            report=self.transform(SOURCE,control,"control-regions")
            active=[f for f in report["functions"] if f["status"]=="control-transformed"]
            self.assertEqual(len(active),7)
            self.assertTrue(all(f["verification"]=="proved-under-model" and f["context_bindings_verified"] for f in active))
            self.assertGreater(sum(r["loops_lowered"] for f in active for r in f["control_regions"]),0)
            self.assertTrue(any(r["outer_continue"] for f in active for r in f["control_regions"]))
            self.assertEqual(control.read_text().count("\n"),SOURCE.read_text().count("\n"))
            first=control.read_bytes();self.transform(SOURCE,control,"control-regions");self.assertEqual(first,control.read_bytes())
            self.transform(SOURCE,root / "seed.c","control-regions",0)
            self.assertNotEqual(first,(root / "seed.c").read_bytes())
            affine=root / "affine.c";self.transform(SOURCE,affine,"private-regions")
            ac=root / "affine-control.c";self.transform(affine,ac,"control-regions")
            ca=root / "control-affine.c";self.transform(control,ca,"private-regions")
            for compiler,version,family in compilers():
                profiles=[("O0",["-O0"]),("O2",["-O2"])]
                if family=="clang": profiles.append(("sanitize",["-O1","-fsanitize=address,undefined","-fno-omit-frame-pointer"]))
                for profile,flags in profiles:
                    common=[compiler,"-std=c11","-pedantic-errors","-Wall","-Wextra","-Werror",*flags]
                    # GCC's uninitialized-value warning does not follow the
                    # verified dispatcher invariant. Keep it visible; it is
                    # nonfatal in this experiment, not suppressed in the tool.
                    if family=="gcc": common.append("-Wno-error=maybe-uninitialized")
                    original=root / "original.o"
                    redirects=["-Dmalloc=csrd_test_malloc","-Dfree=csrd_test_free"]
                    execute([*common,*redirects,*[f"-D{name}=original_{name}" for name in NAMES],"-c",SOURCE,"-o",original])
                    for source in (control,ac,ca):
                        with self.subTest(compiler=version,profile=profile,variant=source.name):
                            obj=root / "candidate.o";binary=root / "compare"
                            compilation=execute([*common,*redirects,*[f"-D{name}=variant_{name}" for name in NAMES],"-c",source,"-o",obj])
                            if "[-Wmaybe-uninitialized]" in compilation.stderr:
                                print(f"DIAGNOSTIC {version}/{profile}/{source.name}: GCC maybe-uninitialized; ordered effect tests required")
                            execute([*common,original,obj,ROOT / "tests/differential/control_driver.c","-o",binary])
                            execute([binary,root / "stream.dat"])

    def test_lifetimes_and_nontermination(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root / "input.c";output=root / "output.c"
            source.write_text("int f(int x){int *p;p=(int[]){x,7};x+=1;x+=p[1];return x;}\n"
                              "int main(void){return f(3)!=11;}\n")
            report=self.transform(source,output,"control-regions")
            self.assertTrue(report["functions"][0]["control_regions"])
            for compiler,_,_ in compilers():
                binary=root / "lifetime"
                execute([compiler,"-std=c11","-O2",output,"-o",binary]);execute([binary])
            source.write_text("int f(void){for(;;){}}\nint main(void){return f();}\n")
            self.transform(source,output,"control-regions")
            for compiler,_,_ in compilers():
                for path in (source,output):
                    binary=root / "divergence"
                    execute([compiler,"-std=c11","-O2","-Wall","-Werror",path,"-o",binary])
                    with self.assertRaises(subprocess.TimeoutExpired):
                        subprocess.run([str(binary)],capture_output=True,timeout=.15)

    def test_nested_loop_and_switch_targets(self):
        # Cross product of structured loops, with/without an unlowered switch.
        # Compile the source independently; no expected dispatcher is assumed.
        def loop(kind, variable, content):
            if kind == "for": return f"for({variable}=0;{variable}<limit;++{variable}){{{content}}}"
            body=f"++{variable};{content}"
            if kind == "while": return f"{variable}=0;while({variable}<limit){{{body}}}"
            return f"{variable}=0;do{{{body}}}while({variable}<limit);"
        functions=[]
        for boundary in (False,True):
            for outer in ("for","while","do"):
                for inner in ("for","while","do"):
                    name=f"f_{len(functions)}"
                    body="if((x&7u)==0u){x+=3u;continue;}if((x&31u)==11u)break;x=x*5u+j;"
                    if boundary:
                        body="switch((x^i^j)&3u){case 0:{x+=3u;if(x&1u)continue;break;}case 1:{x^=i+7u;break;}default:x+=j;}"+body
                    inner_text=loop(inner,"j",body)+"if((x&255u)==37u)return x;x^=i;"
                    functions.append((name,f"unsigned {name}(unsigned x,unsigned limit){{unsigned i,j;limit=(limit&3u)+1u;{loop(outer,'i',inner_text)}return x;}}\n"))
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/"input.c";candidate=root/"output.c";harness=root/"check.c"
            source.write_text("".join(text for _,text in functions))
            proof=self.transform(source,candidate,"control-regions",18446744073709551615)
            self.assertEqual(len([f for f in proof["functions"] if f["status"]=="control-transformed"]),18)
            declarations="".join(f"unsigned original_{n}(unsigned,unsigned),variant_{n}(unsigned,unsigned);\n" for n,_ in functions)
            checks="".join(f"if(original_{n}(x,i)!=variant_{n}(x,i))return 1;" for n,_ in functions)
            harness.write_text(declarations+f"int main(void){{unsigned x=0xffffffffu;for(unsigned i=0;i<512u;++i){{x=x*1664525u+1013904223u;{checks}}}return 0;}}\n")
            for compiler,_,family in compilers():
                flags=[compiler,"-std=c11","-O2","-Wall","-Wextra","-Werror"]
                if family=="gcc": flags.append("-Wno-error=maybe-uninitialized")
                for prefix,path in (("original",source),("variant",candidate)):
                    execute([*flags,*[f"-D{n}={prefix}_{n}" for n,_ in functions],"-c",path,"-o",root/f"{prefix}.o"])
                binary=root/"check"
                execute([*flags,harness,root/"original.o",root/"variant.o","-o",binary]);execute([binary])

    def test_unsupported_context_and_options(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root / "input.c";output=root / "output.c"
            source.write_text("unsigned f(volatile unsigned *p){*p+=1;return *p;}\n")
            report=self.transform(source,output,"control-regions")
            self.assertEqual(report["functions"][0]["status"],"unchanged")
            self.assertIn("volatile",report["functions"][0]["reason"])
            self.assertEqual(source.read_bytes(),output.read_bytes())
            result=subprocess.run([TOOL,"transform",str(source),"-o",str(output),"--scope","control-regions","--strategy","affine"],capture_output=True)
            self.assertEqual(result.returncode,2)


if __name__=="__main__": unittest.main()
