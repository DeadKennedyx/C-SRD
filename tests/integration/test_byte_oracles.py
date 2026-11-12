"""Check independent byte observation labels against compiled benign fixtures."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))
from byte_observation_cases import cases, driver, expected, FUNCTIONS, LAYOUTS
from fit_buffer_traces import location_scope


class ByteOracles(unittest.TestCase):
    def test_basis_perturbs_each_byte(self):
        first,_,changed,*_=cases()
        for a,b in zip(first["memory"],changed["memory"]):
            for i in range(4):self.assertEqual(((b>>(8*i))-(a>>(8*i)))&255,1)

    def test_byte_locations_are_caller_memory(self):
        self.assertEqual(location_scope("0:caller-byte:7"),"caller-memory")

    def test_compiled_fixture_effects(self):
        compiler=shutil.which("clang") or shutil.which("cc")
        if not compiler:self.skipTest("no C compiler")
        macros=subprocess.check_output([compiler,"-dM","-E","-x","c","/dev/null"],text=True)
        signed="__CHAR_UNSIGNED__" not in macros
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for function in sorted(FUNCTIONS):
                kind="char-buffer" if function=="bytes_string" else "signed-char-buffer" if function=="bytes_signed" else "unsigned-char-buffer"
                parameters=[{"kind":kind,"read_only":function=="bytes_string"},{"kind":"uint32-buffer","read_only":False},{"kind":"uint32","read_only":False}]
                harness=root/"driver.c";harness.write_text(driver(function,parameters))
                binary=root/"run"
                subprocess.run([compiler,"-std=c11","-O2","-Wall","-Wextra","-Werror",ROOT/"tests/fixtures/bytes.c",harness,"-o",binary],check=True,capture_output=True)
                for p,q in LAYOUTS:
                    for vector in cases():
                        wanted=expected(function,vector["memory"],p,q,vector["x"],plain_char_signed=signed)
                        inputs=" ".join(map(str,[p,q,vector["x"],*vector["memory"]]))+"\n"
                        observed=list(map(int,subprocess.check_output([binary],input=inputs,text=True).split()))
                        self.assertEqual(observed,[wanted["return_value"],*wanted["final_memory"]],(function,p,q,vector["x"]))


if __name__=="__main__":unittest.main()
