import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/differential"))
from run import compilers, execute
TOOL = str(Path(sys.argv.pop(1)).resolve())


class Algorithms(unittest.TestCase):
    def test_verified_algorithms_compile_and_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = ROOT / "benchmarks/algorithms/popcount8.c"
            driver = root / "driver.c"
            driver.write_text('''#include <stdint.h>
uint32_t popcount8(uint32_t);
int main(void){
    for(unsigned high=0;high<2;++high){
        for(unsigned x=0;x<256;++x){
            unsigned expected=0;
            for(unsigned i=0;i<8;++i){expected+=(x>>i)&1u;}
            if(popcount8(x+(high?4294967040u:0u))!=expected){return 1;}
        }
    }
    return 0;
}
''')
            for algorithm in ("popcount8-swar", "popcount8-serial"):
                for strategy in ("identity", "planned"):
                    output, report = root / "variant.c", root / "report.json"
                    execute([TOOL, "transform", source, "-o", output, "--algorithm", algorithm, "--strategy", strategy, "--report", report])
                    record = json.loads(report.read_text())["functions"][0]
                    self.assertEqual(record["verification"], "proved-under-model")
                    self.assertEqual(record["algorithm_candidate"], algorithm)
                    for compiler, _, _ in compilers():
                        for optimization in ("-O0", "-O2"):
                            binary = root / "compare"
                            execute([compiler, "-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", optimization,
                                     output, driver, "-o", binary])
                            execute([binary])

    def test_non_equivalent_algorithm_never_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "original.c"; output = root / "candidate.c"
            report = root / "report.json"
            source.write_text("#include <stdint.h>\nuint32_t f(uint32_t x){return x;}\n")
            output.write_text("existing artifact\n")
            result = subprocess.run([TOOL, "transform", str(source), "-o", str(output), "--algorithm", "popcount8-swar", "--report", str(report)], capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(output.read_text(), "existing artifact\n")
            self.assertEqual(json.loads(report.read_text())["functions"][0]["verification"], "counterexample")


if __name__ == "__main__":
    unittest.main()
