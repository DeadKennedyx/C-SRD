"""Private scalar regions: context preservation, exclusions and event differential tests."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/differential"))
from run import compilers

TOOL = str(Path(sys.argv.pop(1)).resolve())


class PrivateRegions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.input, self.output, self.report = (self.root / s for s in ("input.c", "output.c", "report.json"))

    def tearDown(self): self.temp.cleanup()

    def call(self, *args, code=0):
        r = subprocess.run([TOOL, *map(str, args)], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, code, r.stderr)
        return r

    def transform(self, source, *options):
        self.input.write_text(source if source.endswith("\n") else source+"\n")
        self.call("transform", self.input, "-o", self.output, "--scope", "private-regions", "--report", self.report, *options)
        return json.loads(self.report.read_text())

    def test_real_context_and_deterministic_source(self):
        source = (ROOT / "tests/fixtures/private_regions.c").read_text()
        for seed in (0, 42, 18446744073709551615):
            r = self.transform(source, "--seed", seed)
            self.assertEqual([f["status"] for f in r["functions"]], ["regions-transformed"]*2)
            self.assertTrue(all(f["verification"] == "proved-under-model" for f in r["functions"]))
            frames = sorted([g for f in r["functions"] for g in f["private_regions"]], key=lambda g:g["candidate_begin"])
            self.assertEqual(len(frames), 3)
            output = self.output.read_bytes()
            self.assertEqual(hashlib.sha256(output).hexdigest(), r["candidate_sha256"])
            restored = output
            for g in reversed(frames):
                emitted = output[g["candidate_begin"]:g["candidate_end"]]
                original = source.encode()[g["source_begin"]:g["source_end"]]
                self.assertEqual(hashlib.sha256(emitted).hexdigest(), g["emitted_fragment_sha256"])
                self.assertEqual(emitted.count(b"\n"), original.count(b"\n"))
                self.assertEqual(g["proof"]["status"], "proved-under-model")
                restored = restored[:g["candidate_begin"]] + original + restored[g["candidate_end"]:]
            self.assertEqual(restored, source.encode())
            self.transform(source, "--seed", seed)
            self.assertEqual(output, self.output.read_bytes())
        self.call("analyze", self.input, "--scope", "private-regions", "--report", self.report)
        self.assertEqual([f["status"] for f in json.loads(self.report.read_text())["functions"]], ["supported-regions"]*2)
        self.call("transform", self.input, "-o", self.output, "--scope", "private-regions", "--strategy", "xor", code=2)
        self.call("verify", self.input, self.output, "--scope", "private-regions", code=2)

    def test_escape_types_macro_and_shadow_boundaries(self):
        cases = [
            ("extern void save(unsigned int*);unsigned int f(unsigned int x){save(&x);x=x+1u;return x;}", "private"),
            ("unsigned int f(unsigned int x){static unsigned int y;y=x+1u;return y;}", "private"),
            ("unsigned int f(volatile unsigned int x){x=x+1u;return x;}", "private"),
            ("unsigned int f(unsigned int x){unsigned int y=0;{unsigned int y=1;y=y+x;}return y;}", "shadow"),
            ("#define STEP(x) ((x)+1u)\nunsigned int f(unsigned int x){x=STEP(x);return x;}\n", "macro"),
            ("int f(int x){x=x+1;return x;}", "private"),
            ("unsigned int f(unsigned int x,unsigned int y){x=x*y;return x;}", "private"),
        ]
        for source, reason in cases:
            with self.subTest(source=source):
                r = self.transform(source)
                self.assertEqual(r["functions"][0]["status"], "unchanged")
                self.assertIn(reason, r["functions"][0]["reason"])
                self.assertEqual(self.output.read_text(), self.input.read_text())

    def test_partial_escape_and_collision(self):
        source = "extern void save(unsigned int*);unsigned int f(unsigned int x,unsigned int y){save(&y);y=y+1u;x=x+1u;x=x+2u;return x+y;}"
        r = self.transform(source)
        f, = r["functions"]; g, = f["private_regions"]
        self.assertEqual(g["inputs"], ["x"]); self.assertEqual(g["outputs"], ["x"])
        # Reserve the exact first proposed name in a preprocessor branch.
        prefix = "#if 0\ncsrd_frame_"; suffix = "_0\n#endif\n"
        offset = g["source_begin"] + len(prefix) + len(suffix) + 3
        for _ in range(4): offset = g["source_begin"] + len(prefix) + len(suffix) + len(str(offset))
        guarded = prefix + str(offset) + suffix + source
        r = self.transform(guarded)
        g = r["functions"][0]["private_regions"][0]
        self.assertEqual(g["source_begin"], offset)
        emitted = self.output.read_text()[g["candidate_begin"]:g["candidate_end"]]
        self.assertNotIn(f"unsigned int csrd_frame_{offset}_0 =", emitted)

    def test_compiled_events_memory_and_return(self):
        source = (ROOT / "tests/fixtures/private_regions.c").read_text()
        harness = self.root / "harness.c"; harness.write_text(HARNESS)
        builds = checks = 0
        for strategy, seed in (("identity",0),("affine",0),("affine",42),("affine",18446744073709551615)):
            self.transform(source, "--strategy", strategy, "--seed", seed)
            for compiler, _, family in compilers():
                profiles = [["-O0"], ["-O2"], ["-O3"], ["-Os"]]
                if family == "clang": profiles.append(["-O1", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"])
                for flags in profiles:
                    with self.subTest(strategy=strategy, seed=seed, compiler=compiler, flags=flags):
                        common = [compiler, "-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", *flags]
                        for prefix, path in (("original",self.input),("candidate",self.output)):
                            command = [*common, f"-Dregion_pipeline={prefix}_pipeline", f"-Dregion_outputs={prefix}_outputs",
                                       "-c", str(path), "-o", str(self.root / (prefix+".o"))]
                            subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
                        program = self.root / "check"
                        subprocess.run([*common, str(harness), str(self.root/"original.o"), str(self.root/"candidate.o"), "-o", str(program)],
                                       check=True, capture_output=True, text=True, timeout=60)
                        r = subprocess.run([str(program)], capture_output=True, text=True, timeout=60)
                        self.assertEqual(r.returncode, 0, r.stdout+r.stderr)
                        self.assertIn("checks=3078", r.stdout); builds += 1; checks += 3078
        print(f"private regions: {builds} compiler/profile/variant cells; {checks} return/memory/event comparisons", flush=True)


HARNESS = r'''#include <stdint.h>
#include <stdio.h>
#include <string.h>
uint32_t original_pipeline(uint32_t*,uint32_t,int);
uint32_t candidate_pipeline(uint32_t*,uint32_t,int);
int original_outputs(uint32_t*,uint32_t,uint32_t);
int candidate_outputs(uint32_t*,uint32_t,uint32_t);
static uint32_t events[64], count, *memory;
void record_event(uint32_t value){events[count++]=value;}
uint32_t next_value(uint32_t value){record_event(value);memory[1]+=value;return value+memory[1];}
static uint32_t state=0x43535244u;
static uint32_t next(void){state^=state<<13;state^=state>>17;state^=state<<5;return state;}
int main(void){
 const uint32_t edges[]={0u,1u,2147483647u,2147483648u,4294967294u,4294967295u};
 for(unsigned i=0;i<1026;i++){
  uint32_t x=i<6?edges[i]:next(), y=i<6?edges[(i+1)%6]:next();
  for(int scenario=0;scenario<3;scenario++){
   uint32_t a[3]={y,x,0x12345678u},b[3];memcpy(b,a,sizeof a);
   uint32_t expected_events[64], expected_count;
   memset(events,0,sizeof events); count=0;memory=a;
   uint32_t ra=scenario==2?(uint32_t)original_outputs(a,x,y):original_pipeline(a,x,scenario==0?-1:(int)(i%9));
   memcpy(expected_events,events,sizeof events);expected_count=count;
   memset(events,0,sizeof events);count=0;memory=b;
   uint32_t rb=scenario==2?(uint32_t)candidate_outputs(b,x,y):candidate_pipeline(b,x,scenario==0?-1:(int)(i%9));
   if(ra!=rb||memcmp(a,b,sizeof a)||count!=expected_count||memcmp(events,expected_events,sizeof events)){
    fprintf(stderr,"mismatch i=%u scenario=%d\n",i,scenario);return 1;
   }
  }
 }
 puts("checks=3078");return 0;
}
'''


if __name__ == "__main__": unittest.main()
