"""Check global planning against exhaustive enumeration and expanded C rejection."""
import itertools
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOL = str(Path(sys.argv.pop(1)).resolve())


class Planning(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def transform(self, body, *options, preamble=""):
        source = self.root / "in.c"
        output = self.root / "out.c"
        report = self.root / "report.json"
        text = "#include <stdint.h>\n" + preamble + "uint32_t f(uint32_t x,uint32_t y){" + body + "}\n"
        source.write_text(text)
        result = subprocess.run([TOOL, "transform", str(source), "-o", str(output), "--report", str(report), *options], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(report.read_text())["functions"][0], output.read_text(), text

    def test_plan_matches_exhaustive_optimum(self):
        body = "uint32_t a=x+y; uint32_t b=a^y; uint32_t c=b&x; uint32_t d=c+1u; return d+a;"
        for objective, coverage in itertools.product(["balanced", "runtime", "size"], [0, 50, 100]):
            with self.subTest(objective=objective, coverage=coverage):
                record, _, _ = self.transform(body, "--strategy", "planned", "--coverage", str(coverage), "--objective", objective)
                self.assertEqual(record["verification"], "proved-under-model")
                self.assertEqual(record["planner_status"], "optimized")
                graph = record["graph"]
                choices = [[0, 1] if n["operation"] in ("add", "subtract", "scale") else
                           [0, 2] if n["operation"] in ("xor", "and", "or", "not", "shl", "lshr") else [0] for n in graph]
                def costs(labels):
                    conversions = set()
                    operations = 0
                    for n, label in zip(graph, labels):
                        if n["operation"] in ("parameter", "constant"):
                            continue
                        operations += 1 if label == 0 else 4 if label == 2 and n["operation"] in ("and", "or") else 2
                        for p in n["inputs"]:
                            if graph[p]["operation"] != "constant" and labels[p] != label:
                                conversions.add((p, label))
                    if labels[-1] != 0:
                        conversions.add((len(graph)-1, 0))
                    price = [0, 2, 1]
                    operations += sum(price[labels[p]] + price[target] for p, target in conversions)
                    count = len(conversions)
                    statements = sum(n["operation"] not in ("parameter", "constant") for n in graph) + count
                    ordinary = sum(label == 0 and n["operation"] not in ("parameter", "constant") for n, label in zip(graph, labels))
                    score = operations if objective == "runtime" else statements if objective == "size" else operations + 2*count + statements
                    return score, count, ordinary, sum((i+1)*label for i, label in enumerate(labels))
                candidates = [labels for labels in itertools.product(*choices) if sum(label != 0 for label in labels) >= record["required_encoded_operations"]]
                actual = [{"identity-u32": 0, "affine-u32": 1, "xor-u32": 2}[n["representation"]] for n in graph]
                self.assertEqual(costs(actual), min(map(costs, candidates)))

    def test_conversion_sharing_beats_independent_baseline(self):
        body = "uint32_t a=x+y; uint32_t b=a*3u; uint32_t c=a*7u; return b+c;"
        uniform, _, _ = self.transform(body, "--strategy", "affine")
        independent, _, _ = self.transform(body, "--strategy", "independent")
        self.assertEqual(uniform["internal_conversions"], 0)
        self.assertGreater(independent["internal_conversions"], uniform["internal_conversions"])

    def test_reject_unsafe_expansions(self):
        bodies = [
            "uint32_t a[4]={1u,2u,3u,4u}; return a[x];",
            "uint32_t a[4]={1u,2u,3u,4u}; return a[4];",
            "uint32_t a[4]={1u,2u,3u,4u}; a[0]=x; return a[0];",
            "uint32_t a[4]={x,2u,3u,4u}; return a[0];",
            "uint32_t a[4]={[2]=7u}; return a[0];",
            "uint32_t a[4]={1u,2u,3u,4u}; uint32_t index=0u; for(uint32_t i=0u;i<8u;++i){x=x+a[index]; index=index+1u;} return x;",
            "for(uint32_t i=0u;i<x;++i){y=y+1u;} return y;",
            "for(uint32_t i=0u;i<33u;++i){y=y+1u;} return y;",
            "for(uint32_t i=0u;i<8u;++i){i=i+1u;} return y;",
            "for(uint32_t i=0u;i<8u;--i){y=y+1u;} return y;",
            "for(uint32_t i=0u;i<8u;++i){break;} return y;",
            "if(x){uint32_t a=y; x=a;} return x;",
            "uint32_t a[2]={1u,2u}; uint32_t index=0u; if(x){index=3u;} return a[index];",
        ]
        for body in bodies:
            with self.subTest(body=body):
                record, output, source = self.transform(body)
                self.assertEqual(record["status"], "unchanged")
                self.assertEqual(output, source)

    def test_generated_names_avoid_macros_and_identifiers(self):
        body = "uint32_t csrd_value_0=x; uint32_t csrd_value_1=y; return csrd_value_0+csrd_value_1;"
        record, output, _ = self.transform(body)
        self.assertEqual(record["verification"], "proved-under-model")
        self.assertIn("csrd_value_2", output)
        record, output, _ = self.transform("return x+y;", preamble="#define csrd_value_0 17u\n#if 0\nint csrd_value_1;\n#endif\n")
        self.assertEqual(record["verification"], "proved-under-model")
        self.assertIn("unsigned int csrd_value_2", output)

    def test_large_plan_reports_heuristic_and_respects_coverage(self):
        body = "uint32_t sum=y; for(uint32_t i=0u;i<10u;++i){sum=sum+x+i; x=x^17u;} return sum;"
        for coverage in (0, 50, 100):
            record, first, _ = self.transform(body, "--strategy", "planned", "--coverage", str(coverage))
            self.assertEqual(record["planner_status"], "heuristic")
            self.assertEqual(record["verification"], "proved-under-model")
            eligible = [n for n in record["graph"] if n["operation"] in ("add", "subtract", "scale", "xor", "and", "or", "not", "shl", "lshr")]
            self.assertGreaterEqual(sum(n["representation"] != "identity-u32" for n in eligible), record["required_encoded_operations"])
            _, second, _ = self.transform(body, "--strategy", "planned", "--coverage", str(coverage))
            self.assertEqual(first, second)

    def test_nested_loops_preserve_active_index_bounds(self):
        body = "uint32_t a[2]={3u,7u}; for(uint32_t i=0u;i<2u;++i){for(uint32_t j=0u;j<2u;++j){x=x+a[i]+a[j];}} return x+y;"
        record, _, _ = self.transform(body)
        self.assertEqual(record["verification"], "proved-under-model")


if __name__ == "__main__":
    unittest.main()
