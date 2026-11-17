"""Keep singleton settings and live-app lifecycle validation in a fresh process."""
from pathlib import Path
import importlib.util
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(all(importlib.util.find_spec(name) for name in
    ("fastapi", "chromadb", "openai", "pydantic_settings", "httpx")), "Full backend test dependencies required")
class SystemRuntimeCase(unittest.TestCase):
    def test_real_unified_app_and_persistent_stores(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/validate-system.py")],
            cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr[-6000:] + result.stdout)
        self.assertIn('"external_network_calls": 0', result.stdout)


if __name__ == "__main__":
    unittest.main()
