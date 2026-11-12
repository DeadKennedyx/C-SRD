"""Record layouts, persistent state and alias-sensitive translation validation."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOL = str(Path(sys.argv.pop(1)).resolve())
ROOT = Path(__file__).resolve().parents[2]
PREAMBLE = "#include <stdint.h>\nstruct pair {uint32_t a;uint32_t b;};\nunion word {uint32_t a;uint32_t b;};\n"


class Records(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_tool(self, *args, code=0):
        run = subprocess.run([TOOL, *map(str,args)],capture_output=True,text=True,timeout=60)
        self.assertEqual(run.returncode,code,run.stderr)

    def transform(self,text,*args):
        source=self.root/"a.c";output=self.root/"b.c";report=self.root/"r.json"
        source.write_text(PREAMBLE+text+"\n")
        self.run_tool("transform",source,"-o",output,"--report",report,*args)
        return json.loads(report.read_text())["functions"][0]

    def compare(self,a,b,status="counterexample"):
        source=self.root/"a.c";output=self.root/"b.c";report=self.root/"r.json"
        source.write_text(PREAMBLE+a+"\n");output.write_text(PREAMBLE+b+"\n")
        self.run_tool("verify",source,output,"--report",report,code=0 if status=="proved-under-model" else 3)
        result=json.loads(report.read_text())["functions"][0]
        self.assertEqual(result["verification"],status,result)
        return result

    def test_fixture_transformation_and_layout(self):
        for strategy in ("identity","affine"):
            for seed in (0,42,18446744073709551615):
                report=self.root/"r.json"
                self.run_tool("transform",ROOT/"tests/fixtures/records.c","-o",self.root/"b.c",
                              "--report",report,"--strategy",strategy,"--seed",seed)
                functions=json.loads(report.read_text())["functions"]
                self.assertEqual(len(functions),7)
                for f in functions:
                    self.assertEqual(f["status"],"transformed",f)
                    self.assertEqual(f["verification"],"proved-under-model",f)
                    self.assertEqual(f["semantic_model"],"records-state-byte-c11-v1")
                    self.assertEqual(f["parameters"][0]["record"]["alignment"],4)
                    if strategy=="affine":self.assertGreater(f["operations_without_decoding"],0)

    def test_member_aliases_and_bad_offsets(self):
        self.compare("uint32_t f(struct pair*p,uint32_t*q,uint32_t x){p->b=x;return *q;}",
                     "uint32_t f(struct pair*p,uint32_t*q,uint32_t x){uint32_t v=*q;p->b=x;return v;}")
        self.compare("uint32_t f(struct pair*p,uint32_t x){p->b=x;return 7u;}",
                     "uint32_t f(struct pair*p,uint32_t x){p->a=x;return 7u;}")
        self.compare("uint32_t f(union word*p,uint32_t x){p->a=x;return p->b;}",
                     "uint32_t f(union word*p,uint32_t x){p->b=x;return x;}","proved-under-model")

    def test_persistent_aliases_and_memory_only_corruption(self):
        head="uint32_t g=11u;"
        result=self.compare(head+"uint32_t f(uint32_t*p,uint32_t x){g=x;return *p;}",
                            head+"uint32_t f(uint32_t*p,uint32_t x){uint32_t v=*p;g=x;return v;}")
        self.assertTrue(result["proof"]["memory_cells"])
        self.compare(head+"uint32_t f(uint32_t x){g=x+1u;return 7u;}",
                     head+"uint32_t f(uint32_t x){g=x+2u;return 7u;}")
        self.compare("struct pair g={1u,2u};uint32_t f(uint32_t x){g.a=x;g.b=3u*x;return g.a+g.b;}",
                     "struct pair g={1u,2u};uint32_t f(uint32_t x){g.a=x;g.b=x*3u;return x*4u;}","proved-under-model")

    def test_const_record_and_captured_view(self):
        for source in ("uint32_t f(const struct pair*p,uint32_t x){return p[x&1u].a+x;}",
                       "uint32_t f(struct pair*p,uint32_t x){struct pair*q=p+(x&1u);x=x+1u;q->b=x;return q->a;}"):
            f=self.transform(source)
            self.assertEqual(f["verification"],"proved-under-model",f)
            self.assertEqual(f["parameters"][0]["minimum_elements"],2)

    def test_record_size_edges_and_static_global(self):
        for count in (1,3,16):
            fields="".join(f"uint32_t f{i};" for i in range(count))
            result=self.transform(f"struct R{{{fields}}};uint32_t f(struct R*p,uint32_t x){{p[x&1u].f{count-1}=3u*x+11u;return p->f0+x;}}")
            self.assertEqual(result["verification"],"proved-under-model",result)
            self.assertEqual(result["parameters"][0]["record"]["bytes"],4*count)
        result=self.transform("static uint32_t g=7u;uint32_t f(uint32_t x){g=3u*g+x;return g+1u;}")
        self.assertEqual(result["verification"],"proved-under-model",result)
        fields="".join(f"uint32_t f{i};" for i in range(17))
        result=self.transform(f"struct R{{{fields}}};uint32_t f(struct R*p){{return p->f0;}}")
        self.assertEqual(result["status"],"unchanged")

    def test_layout_and_state_identity_mismatch(self):
        self.compare("struct R{uint32_t a;uint32_t b;};uint32_t f(struct R*p){return p->a;}",
                     "struct R{uint32_t b;uint32_t a;};uint32_t f(struct R*p){return p->a;}","unsupported")
        self.compare("uint32_t g;uint32_t f(uint32_t x){g=x;return g;}",
                     "uint32_t h;uint32_t f(uint32_t x){h=x;return h;}","unsupported")

    def test_complete_global_object_and_byte_alias_conditions(self):
        head="struct pair g={1u,2u};"
        self.compare(head+"uint32_t f(struct pair*p,uint32_t x){p->a=x;return g.b;}",
                     head+"uint32_t f(struct pair*p,uint32_t x){uint32_t v=g.b;p->a=x;return v;}","proved-under-model")
        self.compare(head+"uint32_t f(struct pair*p,uint32_t x){p->a=x;return g.a;}",
                     head+"uint32_t f(struct pair*p,uint32_t x){uint32_t v=g.a;p->a=x;return v;}")
        self.compare("uint32_t f(struct pair*p,unsigned char*q,uint32_t x){p->a=x;return q[0];}",
                     "uint32_t f(struct pair*p,unsigned char*q,uint32_t x){uint32_t v=q[0];p->a=x;return v;}")

    def test_reused_stored_value_and_commuted_arithmetic(self):
        head="struct pair g={3u,7u};uint32_t f(struct pair*p,uint32_t*q,uint32_t x)"
        self.compare(head+"{uint32_t v=g.a+x;g.b=5u*v+7u;q[0]=g.b;p->a=g.a+q[0];return p->a+g.b;}",
                     head+"{uint32_t v=x+g.a;uint32_t w=5u*v+7u;g.b=w;q[0]=w;uint32_t z=w+g.a;p->a=z;return w+z;}",
                     "proved-under-model")

    def test_unsupported_records_and_state_unchanged(self):
        cases=(
            "struct R{unsigned char a;uint32_t b;};uint32_t f(struct R*p){return p->b;}",
            "struct R{uint32_t a:4;};uint32_t f(struct R*p){return p->a;}",
            "struct R{uint32_t a[2];};uint32_t f(struct R*p){return p->a[0];}",
            "struct R{volatile uint32_t a;};uint32_t f(struct R*p){return p->a;}",
            "uint32_t f(struct pair*p){struct pair q=*p;return q.a;}",
            "uint32_t f(struct pair*p,struct pair*q){*p=*q;return p->a;}",
            "uint32_t f(struct pair*p){uint32_t*q=&p->a;return *q;}",
            "uint32_t f(uint32_t x){static uint32_t g=1;g=x;return g;}",
            "volatile uint32_t g;uint32_t f(void){return g;}",
            "_Atomic(uint32_t) g;uint32_t f(void){return g;}",
            "_Thread_local uint32_t g;uint32_t f(void){return g;}",
            "uint32_t g;uint32_t f(void){uint32_t x=g;uint32_t g=1;return x+g;}",
        )
        for source in cases:
            with self.subTest(source=source):
                f=self.transform(source)
                self.assertEqual(f["status"],"unchanged",f)
                self.assertTrue(f["reason"])
                self.assertEqual((self.root/"a.c").read_bytes(),(self.root/"b.c").read_bytes())


if __name__=="__main__":unittest.main()
