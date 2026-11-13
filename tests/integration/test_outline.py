import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tests/differential"))
from run import compilers, execute
TOOL=str(Path(sys.argv.pop(1)).resolve())
SOURCE=ROOT/"tests/fixtures/outline.c"
NAMES=["outline_calculate","outline_signed","outline_byte","outline_select",
       "outline_logical","outline_buffer","outline_shadow"]


class Outline(unittest.TestCase):
    def transform(self,source,output,scope="outline-regions",seed=42):
        report=output.with_suffix(".json")
        execute([TOOL,"transform",source,"-o",output,"--scope",scope,"--seed",str(seed),"--report",report])
        data=json.loads(report.read_text())
        for row in data["functions"]:
            if row["status"]!="unchanged":
                self.assertEqual(row["verification"],"proved-under-model")
                self.assertTrue(row["context_bindings_verified"])
        return data

    def test_values_effects_and_composition(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);outlined=root/"outlined.c"
            data=self.transform(SOURCE,outlined)
            self.assertEqual({r["function"] for r in data["functions"] if r["status"]=="outline-transformed"},set(NAMES))
            self.assertEqual(outlined.read_text().count("\n"),SOURCE.read_text().count("\n"))
            copy=root/"copy.c";self.transform(SOURCE,copy)
            self.assertEqual(copy.read_bytes(),outlined.read_bytes())
            self.transform(SOURCE,copy,seed=18446744073709551615)
            self.assertNotEqual(copy.read_bytes(),outlined.read_bytes())
            variants=[outlined]
            for index,scopes in enumerate([
                ["outline-regions","private-regions"],["private-regions","outline-regions"],
                ["outline-regions","control-regions"],["control-regions","outline-regions"],
                ["private-regions","outline-regions","control-regions"],
                ["control-regions","outline-regions","private-regions"],
            ]):
                current=SOURCE
                for step,scope in enumerate(scopes):
                    output=root/f"pipeline-{index}-{step}.c"
                    self.transform(current,output,scope);current=output
                variants.append(current)
            for compiler,version,family in compilers():
                profiles=[("O0",["-O0"]),("O2",["-O2"])]
                if family=="clang": profiles.append(("sanitize",["-O1","-fsanitize=address,undefined","-fno-omit-frame-pointer"]))
                for profile,flags in profiles:
                    common=[compiler,"-std=c11","-pedantic-errors","-Wall","-Wextra","-Werror",*flags]
                    if family=="gcc": common.append("-Wno-error=maybe-uninitialized")
                    original=root/"original.o"
                    execute([*common,*[f"-D{n}=original_{n}" for n in NAMES],"-c",SOURCE,"-o",original])
                    for variant in variants:
                        with self.subTest(compiler=version,profile=profile,variant=variant.name):
                            obj=root/"candidate.o";binary=root/"compare"
                            execute([*common,*[f"-D{n}=variant_{n}" for n in NAMES],"-c",variant,"-o",obj])
                            execute([*common,original,obj,ROOT/"tests/differential/outline_driver.c","-o",binary])
                            execute([binary])

    def test_unsafe_capture_macros_and_locations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/"source.c";output=root/"output.c"
            for text in [
                "unsigned f(unsigned c){unsigned x;unsigned y=c?x+1u:0u;return y;}\n",
                "unsigned f(unsigned c,unsigned x){unsigned y=0;return (y=c?x*3u+1u:0u)+(x=5u);}\n",
                "unsigned f(unsigned x){unsigned*p=&x;return x*3u+1u;}\n",
                "unsigned f(volatile unsigned x){return x*3u+1u;}\n",
                "#define TIMES 3u\nunsigned f(unsigned x){return x*TIMES+1u;}\n",
                "unsigned f(unsigned x){return x*3u+1u;} unsigned g(void){return __builtin_COLUMN();}\n",
                "unsigned f(unsigned x){return x*3u+1u;} enum {column=__builtin_COLUMN()}; unsigned g(void){return column;}\n",
            ]:
                source.write_text(text);data=self.transform(source,output)
                self.assertEqual(source.read_bytes(),output.read_bytes())
                self.assertTrue(all(r["status"]=="unchanged" for r in data["functions"]))
            result=subprocess.run([TOOL,"transform",str(source),"-o",str(output),"--scope","outline-regions","--strategy","affine"],capture_output=True)
            self.assertEqual(result.returncode,2)


if __name__=="__main__": unittest.main()
