import ast
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from headroom_recursion import CallResult, CallableClient, CommandClient, ManualClient
from headroom_recursion.clients import TransportError
from headroom_recursion import lean_oracle

ROOT = Path(__file__).resolve().parents[1]
REQUEST = dict(model="arbitrary-local-model", system="instructions", user="payload",
               max_tokens=321, temperature=.25, use_headroom=False)


class TransportTests(unittest.TestCase):
    def worker(self, source, **kwargs):
        return CommandClient([sys.executable, "-S", "-c", source], **kwargs)

    def test_callable_preserves_opaque_model_and_controls(self):
        captured = {}
        def local(**request):
            captured.update(request)
            return "response"
        self.assertEqual(CallableClient(local).complete(**REQUEST).text, "response")
        self.assertEqual(captured, REQUEST)

    def test_callable_rejects_invalid_return(self):
        with self.assertRaises(TypeError):
            CallableClient(lambda **r: {"text": "bad"}).complete(**REQUEST)

    def test_command_real_json_roundtrip(self):
        code = "import sys,json;r=json.load(sys.stdin);print(json.dumps({'protocol_version':1,'ok':True,'text':json.dumps(r)}))"
        result = self.worker(code).complete(**REQUEST)
        self.assertEqual(json.loads(result.text), dict(protocol_version=1, **REQUEST))

    def test_command_no_shell_prompt_interpolation(self):
        with tempfile.TemporaryDirectory() as temp:
            sentinel = Path(temp) / "must-not-exist"
            request = dict(REQUEST, user=f"; touch {sentinel}; $(touch {sentinel})")
            code = "import sys,json;r=json.load(sys.stdin);print(json.dumps({'protocol_version':1,'ok':True,'text':r['user']}))"
            self.assertEqual(self.worker(code).complete(**request).text, request["user"])
            self.assertFalse(sentinel.exists())

    def test_command_refusal_with_exit_zero(self):
        with self.assertRaises(TransportError):
            self.worker("print('{\"protocol_version\":1,\"ok\":false,\"text\":\"refused\"}')").complete(**REQUEST)

    def test_command_nonzero_exit(self):
        with self.assertRaises(TransportError):
            self.worker("raise SystemExit(2)").complete(**REQUEST)

    def test_command_bad_json(self):
        with self.assertRaises(TransportError):
            self.worker("print('not json')").complete(**REQUEST)

    def test_command_nonobject_json(self):
        with self.assertRaises(TransportError):
            self.worker("print('[]')").complete(**REQUEST)

    def test_command_wrong_protocol(self):
        with self.assertRaises(TransportError):
            self.worker("print('{\"protocol_version\":true,\"ok\":true,\"text\":\"x\"}')").complete(**REQUEST)

    def test_command_string_boolean_is_not_ok(self):
        with self.assertRaises(TransportError):
            self.worker("print('{\"protocol_version\":1,\"ok\":\"true\",\"text\":\"x\"}')").complete(**REQUEST)

    def test_command_duplicate_key(self):
        with self.assertRaises(TransportError):
            self.worker("print('{\"protocol_version\":1,\"ok\":false,\"ok\":true,\"text\":\"x\"}')").complete(**REQUEST)

    def test_command_text_must_be_string(self):
        with self.assertRaises(TransportError):
            self.worker("print('{\"protocol_version\":1,\"ok\":true,\"text\":123}')").complete(**REQUEST)

    def test_command_output_limit(self):
        with self.assertRaises(TransportError):
            self.worker("print('x'*100)", max_output_bytes=20).complete(**REQUEST)

    def test_command_timeout(self):
        with self.assertRaises(TransportError):
            self.worker("import time;time.sleep(2)", timeout_s=.05).complete(**REQUEST)

    def test_command_requires_argv_not_shell_string(self):
        with self.assertRaises(ValueError):
            CommandClient("python worker.py")

    def test_manual_exchange(self):
        writer = io.StringIO()
        result = ManualClient(reader=io.StringIO("line one\nline two\nEND\n"), writer=writer).complete(**REQUEST)
        self.assertEqual(result.text, "line one\nline two")
        self.assertIn(REQUEST["model"], writer.getvalue())

    def test_manual_eof_is_failure(self):
        with self.assertRaises(EOFError):
            ManualClient(reader=io.StringIO("unfinished"), writer=io.StringIO()).complete(**REQUEST)

    def test_callresult_rejects_bad_accounting(self):
        for kwargs in [dict(text=None), dict(text="x", tokens_before=True),
                       dict(text="x", tokens_after=-1), dict(text="x", cost_usd=float("nan"))]:
            with self.subTest(kwargs=kwargs), self.assertRaises((ValueError, TypeError)):
                CallResult(**kwargs)

    def invoke(self, *args):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
        return subprocess.run([sys.executable, "-S", "-m", "headroom_recursion", *args],
                              env=env, cwd=ROOT, capture_output=True, text=True, timeout=10)

    def test_cli_demo_without_site_packages(self):
        result = self.invoke("--demo", "--n", "1", "--steps", "8", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["stop_reason"], "validated")
        self.assertEqual(data["total_calls"], 14)

    def test_cli_requires_explicit_transport(self):
        self.assertEqual(self.invoke("an arbitrary problem").returncode, 2)

    def test_cli_demo_does_not_answer_other_tasks(self):
        self.assertEqual(self.invoke("--demo", "some other task").returncode, 2)

    def test_cli_dry_run_needs_no_backend(self):
        self.assertEqual(self.invoke("--dry-run").returncode, 0)

    def test_cli_json_command_without_service(self):
        argv = json.dumps([sys.executable, str(ROOT / "examples" / "local_worker.py")])
        result = self.invoke("--command-json", argv, "--n", "1", "--steps", "1", "arithmetic demo")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("local", result.stdout)

    def test_runtime_has_no_network_client_imports(self):
        forbidden = {"requests", "httpx", "aiohttp", "urllib", "http", "socket"}
        for path in (ROOT / "src").rglob("*.py"):
            tree = ast.parse(path.read_text())
            names = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names += [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names.append(node.module.split(".")[0])
            self.assertFalse(forbidden & set(names), path)


class LeanTests(unittest.TestCase):
    def test_execution_disabled_by_default(self):
        with self.assertRaises(ValueError):
            lean_oracle.make_gate_oracle()

    def test_axiom_allowlist(self):
        ok, _ = lean_oracle.audit_axioms("'target' depends on axioms: [propext, Classical.choice, Quot.sound]", "target")
        self.assertTrue(ok)

    def test_axiom_missing_fails(self):
        self.assertFalse(lean_oracle.audit_axioms("compiled", "target")[0])

    def test_axiom_unexpected_fails(self):
        self.assertFalse(lean_oracle.audit_axioms("'target' depends on axioms: [sorryAx]", "target")[0])

    def test_axiom_conflicting_records_fail(self):
        output = "'target' does not depend on any axioms\n' target' depends on axioms: [sorryAx]"
        # Only the exact declaration is considered; duplicate exact records fail.
        duplicate = "'target' does not depend on any axioms\n' target' does not depend on any axioms".replace("' target'", "'target'")
        self.assertFalse(lean_oracle.audit_axioms(duplicate, "target")[0])

    def test_gate_pass_is_insufficient_with_mock_compiler(self):
        runner = lambda *a, **k: subprocess.CompletedProcess(a, 0, "", "")
        gate = lean_oracle.make_gate_oracle(trusted_execution=True, runner=runner)
        self.assertFalse(gate.sufficient)
        self.assertTrue(gate.validator("```lean\ntheorem x : True := by trivial\n```").passed)

    def test_pinned_statement_and_mock_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            skeleton = Path(temp) / "Target.lean"
            text = "-- LEAN-ORACLE-TARGET: target\ntheorem target : True :=\n  sorry\n"
            skeleton.write_text(text)
            seen = []
            def runner(argv, **kwargs):
                seen.append(Path(argv[-1]).read_text())
                return subprocess.CompletedProcess(argv, 0, "'target' does not depend on any axioms\n", "")
            oracle = lean_oracle.make_decider_oracle(skeleton, trusted_execution=True, runner=runner)
            self.assertTrue(oracle.validator("```lean\nby trivial\n```").passed)
            self.assertTrue(oracle.sufficient)
            self.assertIn("theorem target : True :=", seen[0])
            self.assertEqual(skeleton.read_text(), text)
            self.assertNotIn("sorry", seen[0])

    def test_multiple_proof_blocks_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "Target.lean"
            path.write_text("-- LEAN-ORACLE-TARGET: target\ntheorem target : True :=\n  sorry\n")
            def unexpected(*args, **kwargs):
                raise AssertionError("compiler must not run")
            oracle = lean_oracle.make_decider_oracle(path, trusted_execution=True, runner=unexpected)
            self.assertFalse(oracle.validator("```lean\nby trivial\n```\n```lean\nby trivial\n```").passed)


if __name__ == "__main__":
    unittest.main()
