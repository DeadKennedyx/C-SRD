"""Measurement controls: crypto recognition, analysis failure and backend identity."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from audit_crypto_recognition import Runner, parse_matches, summarize


class CryptoRecognitionControls(unittest.TestCase):
    def test_generic_crypto_match_is_not_aes(self):
        match = parse_matches("crypto-detection", b"BASE64_bytecode_decode_x64 sample.exe\n")
        self.assertFalse(match["aes_recognized"])
        self.assertEqual(match["all_matches"], ["BASE64_bytecode_decode_x64"])

    def test_aes_matches_are_binary_presence_not_hit_count(self):
        match = parse_matches("findcrypt-yara", b"RijnDael_AES_CHAR sample.exe\nRijnDael_AES_LONG sample.exe\n")
        self.assertTrue(match["aes_recognized"])
        self.assertEqual(len(match["aes_matches"]), 2)
        scans = {name: match for name in ("yara-rules", "findcrypt-yara", "crypto-detection", "capa")}
        row = summarize([{"variant": "stock", "scans": scans}])["stock"]["capa"]
        self.assertEqual(row["aes_positive"], 1)
        self.assertEqual(row["successful_scans"], 1)
        self.assertEqual(row["planned"], 7)

    def test_failure_not_counted_as_negative(self):
        scans = {name: {"status": "error", "returncode": 1}
                 for name in ("yara-rules", "findcrypt-yara", "crypto-detection", "capa")}
        row = summarize([{"variant": "stock", "scans": scans}])["stock"]["capa"]
        self.assertEqual(row["successful_scans"], 0)
        self.assertEqual(row["errors"], 1)
        self.assertEqual(row["planned"], 7)

    def test_capa_classification_and_backend(self):
        doc = {"meta": {"analysis": {"extractor": "VivisectFeatureExtractor"}}, "rules": {
            "AES capability": {"meta": {"namespace": "data-manipulation/encryption/aes"}},
            "XOR capability": {"meta": {"namespace": "data-manipulation/encryption/xor"}}}}
        self.assertEqual(parse_matches("capa", json.dumps(doc).encode())["aes_matches"], ["AES capability"])
        doc["meta"]["analysis"]["extractor"] = "PefileFeatureExtractor"
        with self.assertRaises(ValueError):
            parse_matches("capa", json.dumps(doc).encode())
        with self.assertRaises(KeyError):
            parse_matches("capa", b'{}')
        with self.assertRaises(ValueError):
            parse_matches("capa", b'')

    def test_real_subprocess_failure_is_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = Runner(root)
            command = [sys.executable, "-c", "import sys; sys.stderr.write('dependency missing'); sys.exit(7)"]
            with self.assertRaises(RuntimeError): runner.run("fail", command)
            saved = json.loads((root / "commands.json").read_text())
            self.assertEqual(saved[0]["returncode"], 7)
            self.assertEqual((root / "logs/fail.stderr").read_text(), "dependency missing")


if __name__ == "__main__":
    unittest.main()
