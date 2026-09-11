"""Explicit local execution modes; no implicit model or network client."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from . import demo
from .clients import CallableClient, CommandClient, ManualClient, strict_json
from .config import RecurseConfig, Tier
from .workspace import WorkspacePolicy
from .ladder import RunError, plan_schedule, recurse
from .prompts import research_prompt
from .retrieval import CorpusRetriever


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local, provider-neutral recursive refinement")
    parser.add_argument("problem", nargs="?")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--manual", action="store_true", help="exchange visible prompts and responses by hand")
    source.add_argument("--command-json", help='literal JSON argv, e.g. ["python", "my_local_worker.py"]')
    source.add_argument("--demo", action="store_true", help="run a fixed exact-arithmetic demonstration, not a neural model")
    parser.add_argument("--problem-file", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--n", type=int)
    parser.add_argument("--steps", type=int)
    parser.add_argument("--ladder", default="local", help="comma-separated opaque model identifiers, in operator-chosen order")
    parser.add_argument("--judge-model")
    parser.add_argument("--judge-votes", type=int, default=1)
    parser.add_argument("--threshold", type=float, default=0.9)
    parser.add_argument("--max-calls", type=int)
    parser.add_argument("--max-seconds", type=float)
    parser.add_argument("--call-timeout", type=float, default=120)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--research", action="store_true")
    parser.add_argument("--trace-dir", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--profile", choices=("coding", "research"), help="explicit bounded work profile, not a model selector")
    parser.add_argument("--rungs", type=int, help="repeat the one supplied ladder model; no independent-model claim")
    parser.add_argument("--archive-search", action="store_true", help="offered-source literal find in compact workspace")
    parser.add_argument("--memory-db", type=Path, help="host-owned persistent MTM; not an authority database")
    parser.add_argument("--memory-user")
    parser.add_argument("--memory-project")
    parser.add_argument("--memory-controller-model")
    parser.add_argument("--memory-selector-model")
    parser.add_argument("--memory-writer-model")
    parser.add_argument("--memory-k", type=int, default=5)
    parser.add_argument("--memory-capacity", type=int, default=10000)
    parser.add_argument("--efficient", action="store_true", help="compact workspace-v2, local progress carry-forward, exact single-judge reuse")
    parser.add_argument("--no-compression", action="store_true")
    parser.add_argument("--compression-backend", choices=("local", "headroom"), default="local")
    parser.add_argument("--scratchpad-tokens", type=int, default=1536)
    parser.add_argument("--context-tokens", type=int, default=2048)
    parser.add_argument("--max-input-tokens", type=int)
    parser.add_argument("--workspace-tokens", type=int, help="opt into bounded archive/delta prompts; default counter is an estimate, not billing tokens")
    parser.add_argument("--compress-judge-notes", action="store_true")
    parser.add_argument("--no-preseed", action="store_true", help="disable the model's checkpoint-selection call")
    parser.add_argument("--no-progress-guard", action="store_true", help="explicit legacy mode; no seed baseline or monotonic rollback")
    parser.add_argument("--progress-model")
    parser.add_argument("--progress-k", type=int, default=4)
    parser.add_argument("--progress-tokens", type=int, default=1024)
    parser.add_argument("--seed-answer-file", type=Path)
    parser.add_argument("--seed-notes-file", type=Path)
    parser.add_argument("--pin-file", type=Path, action="append", default=[])
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--scope", default="local")
    parser.add_argument("--verification-id", default="")
    args = parser.parse_args(argv)
    def read_text(path):
        if path is None:
            return ""
        with path.open("rb") as file:
            data = file.read(1_000_001)
        if len(data) > 1_000_000:
            raise ValueError("input file exceeds 1 MB")
        return data.decode("utf-8")
    memory_store = None
    try:
        models = args.ladder.split(",")
        if any(not model.strip() for model in models):
            raise ValueError("ladder cannot contain empty identifiers")
        if args.rungs is not None:
            if type(args.rungs) is not int or not 1 <= args.rungs <= 1000 or len(models) != 1:
                raise ValueError("--rungs requires one model and 1..1000 rungs")
            models = models * args.rungs
        n = args.n if args.n is not None else (1 if args.profile == "coding" else 2 if args.profile == "research" else 6)
        steps = args.steps if args.steps is not None else (1 if args.profile else 3)
        cfg = RecurseConfig(n=n, T=steps,
                            ladder=tuple(Tier(model.strip(), max_tokens=args.max_tokens) for model in models),
                            judge_model=args.judge_model, judge_votes=args.judge_votes,
                            halt_threshold=args.threshold, max_total_calls=args.max_calls,
                            max_wall_seconds=args.max_seconds, temperature=args.temperature,
                            use_headroom=not args.no_compression, compression_backend=args.compression_backend,
                            scratchpad_tokens=args.scratchpad_tokens, context_tokens=args.context_tokens,
                            max_input_tokens=args.max_input_tokens, compress_judge=args.compress_judge_notes,
                            workspace=WorkspacePolicy(budget=args.workspace_tokens) if args.workspace_tokens is not None else None,
                            enforce_progress=not args.no_progress_guard, preseed_ladder=not args.no_preseed,
                            progress_model=args.progress_model, progress_k=args.progress_k,
                            progress_tokens=args.progress_tokens, memory_scope=args.scope,
                            seed_answer=read_text(args.seed_answer_file), seed_scratchpad=read_text(args.seed_notes_file),
                            pinned_notes=tuple(read_text(path) for path in args.pin_file),
                            checkpoint_path=args.checkpoint, resume_from=args.resume,
                            verification_id=args.verification_id)
        if args.efficient or args.profile or args.memory_db or args.archive_search:
            if args.no_compression or args.compress_judge_notes:
                raise ValueError("--efficient conflicts with --no-compression/--compress-judge-notes")
            cfg.workspace = WorkspacePolicy(budget=args.workspace_tokens or 4096, compact=True,
                                            chunk_chars=768, max_optional_chunks=6)
            cfg.progress_seed_mode = "local"
            cfg.reuse_exact_judgments = True
            if args.profile or args.archive_search or args.memory_db:
                from dataclasses import replace
                cfg.workspace = replace(cfg.workspace, enable_search=True)
        if args.profile:
            cfg.judge_can_halt = args.profile != "research"
            if cfg.max_total_calls is None:
                cfg.max_total_calls = 2 + len(models) * steps * (3 * (n + 1) + 5)
        if args.memory_db:
            from .memory import MemoryStore, MemoryPolicy, MemorySession, MemoryModels, Principal
            if not args.memory_user or not args.memory_project or not args.verification_id:
                raise ValueError("--memory-db requires explicit --memory-user, --memory-project, and --verification-id")
            policy = MemoryPolicy(k=args.memory_k, capacity=args.memory_capacity)
            principal = Principal(args.memory_user,args.memory_project)
            models = MemoryModels(controller=args.memory_controller_model,selector=args.memory_selector_model,
                                  writer=args.memory_writer_model)
            if not args.dry_run:
                memory_store = MemoryStore(args.memory_db, policy=policy)
                cfg.memory_session = MemorySession(memory_store, principal, models=models)
        elif any((args.memory_user,args.memory_project,args.memory_controller_model,args.memory_selector_model,args.memory_writer_model)):
            raise ValueError("memory options require --memory-db")
        cfg.validate()
        if args.dry_run:
            print(plan_schedule(cfg))
            return 0
        if args.problem is not None and args.problem_file is not None:
            raise ValueError("supply problem text or --problem-file, not both")
        if args.demo:
            if cfg.workspace is not None:
                raise ValueError("the legacy --demo does not emit workspace patches; use examples/workspace_demo.py")
            if args.problem is not None or args.problem_file or args.research:
                raise ValueError("--demo has a fixed mathematical task; it does not answer arbitrary prompts")
            problem, client = demo.PROBLEM, CallableClient(demo.complete)
            cfg.validator = demo.validator
            cfg.verification_id = args.verification_id or "exact-rational-demo-v1"
        else:
            problem = args.problem or ""
            if args.problem_file is not None:
                with args.problem_file.open("rb") as file:
                    data = file.read(1_000_001)
                if len(data) > 1_000_000:
                    raise ValueError("problem file exceeds 1 MB")
                problem = data.decode("utf-8")
            if not problem.strip():
                raise ValueError("provide a nonempty problem")
            if args.manual:
                client = ManualClient()
            elif args.command_json:
                client = CommandClient(strict_json(args.command_json), timeout_s=args.call_timeout)
            else:
                raise ValueError("choose --manual or --command-json; no backend is selected automatically")
            if args.research:
                problem = research_prompt(problem)
        if args.corpus:
            cfg.retriever = CorpusRetriever.from_file(args.corpus)
            cfg.audit_retriever = cfg.retriever
            cfg.claim_audit = True
        try:
            trace = recurse(problem, client=client, config=cfg)
        except RunError as exc:
            trace = exc.trace
        if args.trace_dir:
            trace.persist(args.trace_dir)
        print(json.dumps(trace.to_dict(), indent=2, ensure_ascii=False, allow_nan=False)
              if args.as_json else trace.summary())
        return 130 if trace.stop_reason == "interrupted" else 1 if trace.stop_reason in {
            "failed", "error", "context-budget", "memory-budget", "checkpoint-error", "seed-unscored"} else 0
    except (ValueError, TypeError, OSError, UnicodeError, ImportError) as exc:
        print(f"recurse: {exc}", file=sys.stderr)
        return 2
    finally:
        if memory_store is not None:
            memory_store.close()


if __name__ == "__main__":
    raise SystemExit(main())
