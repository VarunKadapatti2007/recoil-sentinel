"""The `recoil` CLI: gate / publish / run / reset / demo-check / seed /
install-hook / doctor / serve.

Exit codes are the product: `recoil gate` exits 1 on BLOCK and 0 on PASS,
exactly like a failing CI check.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer

from . import config, db
from .gate import GateError, run_gate
from .models import GateReport

app = typer.Typer(
    name="recoil",
    help="Recoil — CI/CD for AI agents: a regression-eval harness and publish gate.",
    no_args_is_help=True,
    add_completion=False,
)

PASS_MARK = "[PASS]"
BLOCK_MARK = "[BLOCK]"


def _conn():
    conn = db.connect()
    db.init_db(conn)
    return conn


def _print_report(report: GateReport) -> None:
    width = 100
    print()
    print("=" * width)
    print(f" RECOIL GATE   candidate: {report.candidate_label}   baseline: {report.baseline_label}")
    print("=" * width)
    header = f" {'case':<52} {'sev':<9} {'baseline -> candidate':<24} {'delta':<6}"
    print(header)
    print("-" * width)
    for c in report.cases:
        base = "-" if c.baseline_passed is None else ("pass" if c.baseline_passed else "FAIL")
        cand = "pass" if c.candidate_passed else "FAIL"
        delta = {
            "regression": "v REG",
            "newly_fixed": "^ FIX",
            "still_passing": "=",
            "still_failing": "=",
            "new_case": "+ NEW",
        }[c.kind]
        title = c.title if len(c.title) <= 50 else c.title[:47] + "..."
        print(f" {title:<52} {c.severity:<9} {base:>8} -> {cand:<11} {delta:<6}")
    print("-" * width)
    print(
        f" {report.passed_count}/{report.total_cases} passing"
        f"   regressions: {len(report.regressed_case_ids)}"
        f"   newly fixed: {len(report.newly_fixed_case_ids)}"
    )
    if report.verdict == "BLOCK":
        print()
        print(f" {BLOCK_MARK} VERDICT: BLOCK — publish refused. Regressed cases:")
        titles = {c.eval_case_id: c for c in report.cases}
        for cid in report.regressed_case_ids:
            c = titles[cid]
            print(f"   - [{c.severity.upper()}] {c.title}")
    else:
        print()
        print(f" {PASS_MARK} VERDICT: PASS — no regressions against {report.baseline_label}.")
    print("=" * width)
    print()


@app.command()
def gate(
    candidate: str = typer.Option(..., "--candidate", "-c", help="Candidate version label or id"),
    baseline: Optional[str] = typer.Option(
        None, "--baseline", "-b", help="Baseline version (defaults to last published)"
    ),
    live: bool = typer.Option(False, "--live", help="Force live judging (ignore cache)"),
    voice: bool = typer.Option(False, "--voice", help="Play the spoken verdict if available"),
) -> None:
    """Run the regression gate. Exits 1 on BLOCK, 0 on PASS."""
    conn = _conn()
    try:
        report = run_gate(
            conn,
            candidate=candidate,
            baseline=baseline,
            use_cache=None if not live else False,
        )
    except GateError as exc:
        typer.secho(f"gate error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    _print_report(report)
    if voice:
        from .voice import speak_verdict

        path = speak_verdict(report.verdict)
        if path:
            print(f" (spoken verdict: {path})")
    raise typer.Exit(code=1 if report.verdict == "BLOCK" else 0)


@app.command()
def publish(
    candidate: str = typer.Option(..., "--candidate", "-c", help="Candidate version label or id"),
    baseline: Optional[str] = typer.Option(None, "--baseline", "-b"),
) -> None:
    """Run the gate; only flip is_published if the verdict is PASS."""
    conn = _conn()
    try:
        report = run_gate(conn, candidate=candidate, baseline=baseline)
    except GateError as exc:
        typer.secho(f"publish error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    _print_report(report)
    if report.verdict == "BLOCK":
        typer.secho(
            f"{BLOCK_MARK} publish REFUSED: {candidate} regresses "
            f"{len(report.regressed_case_ids)} previously-passing case(s).",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)
    from .adapters import get_publish_target

    msg = get_publish_target().publish(conn, report.candidate_version_id)
    typer.secho(f"{PASS_MARK} published: {msg}", fg=typer.colors.GREEN, bold=True)
    raise typer.Exit(code=0)


@app.command()
def run(
    version: str = typer.Option(..., "--version", "-v", help="Agent version label"),
    input: str = typer.Option(
        ..., "--input", "-i", help="Inline JSON or a path to a JSON file with the alert"
    ),
    live: bool = typer.Option(False, "--live", help="Call the live model if configured"),
) -> None:
    """Invoke the agent once: capture trace -> judge -> promote to eval case on FAIL."""
    conn = _conn()
    v = db.resolve_version(conn, version)
    if v is None:
        typer.secho(f"version {version!r} not found", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    path = Path(input)
    payload = json.loads(path.read_text(encoding="utf-8") if path.exists() else input)

    from .agent import run_agent as exec_agent
    from .judge import get_judge
    from .tracing import capture_run

    trace = exec_agent(v, payload, live=live)
    run_id = capture_run(conn, agent_version_id=v["id"], input=payload, trace=trace)
    print(f"run captured: {run_id}  latency={trace['latency_ms']}ms  cost=${trace['total_cost_usd']}")
    print(json.dumps(trace["output"], indent=2))

    expected = payload.get("_expected") or {}
    ground_truth = {
        "expected": expected,
        "constraints": payload.get("_constraints", {"must_not_contain_pii": True}),
        "ground_truth_source": payload.get("ground_truth_ref", "operator-supplied"),
    }
    verdict = get_judge().evaluate(
        input=payload,
        output=trace["output"],
        rubric="Triage decision must match operator ground truth where provided; reason must be PII-free.",
        reference_behavior="Match the operator-recorded correct triage decision.",
        ground_truth=ground_truth,
    )
    status = "PASS" if verdict.passed else "FAIL"
    print(f"judge: {status} (score={verdict.score}) — {verdict.rationale}")
    if not verdict.passed:
        from .evals.promotion import promote_failure_to_case

        case_id = promote_failure_to_case(conn, run_id=run_id, verdict=verdict)
        if case_id:
            print(f"failure FROZEN into regression case {case_id} — the suite just grew itself.")
        else:
            print("identical failure already frozen; suite unchanged.")
    raise typer.Exit(code=0 if verdict.passed else 1)


@app.command()
def reset(
    demo: bool = typer.Option(False, "--demo", help="Restore the pristine seeded demo state"),
) -> None:
    """Reset the database. With --demo, re-seed the full demo state (<2s, idempotent)."""
    if not demo:
        typer.secho("refusing to wipe without --demo (the only supported reset)", err=True)
        raise typer.Exit(code=2)
    import time

    t0 = time.perf_counter()
    config.ensure_dirs()
    conn = db.reset_db()
    from .seeding import seed_all

    summary = seed_all(conn)
    dt = time.perf_counter() - t0
    print(
        f"demo state restored in {dt:.2f}s — {summary['runs']} runs, "
        f"{len(summary['cases'])} frozen cases, published baseline: v_good"
    )


@app.command()
def seed(verbose: bool = typer.Option(True, "--verbose/--quiet")) -> None:
    """Seed the database (same as reset --demo, kept as a familiar alias)."""
    config.ensure_dirs()
    conn = db.reset_db()
    from .seeding import seed_all

    summary = seed_all(conn, verbose=verbose)
    print(f"seeded {summary['runs']} runs, {len(summary['cases'])} cases, 5 versions")


@app.command(name="demo-check")
def demo_check() -> None:
    """Headless end-to-end assertion of the scripted demo path:
    reset -> gate v_regressed (must BLOCK, hero case regressed) ->
    gate v_fixed (must PASS). Exits non-zero with a clear message on any failure."""
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        mark = "ok " if ok else "FAIL"
        print(f" [{mark}] {name}" + (f" — {detail}" if detail and not ok else ""))
        if not ok:
            failures.append(name)

    print("recoil demo-check")
    print("-" * 60)

    config.ensure_dirs()
    conn = db.reset_db()
    from .seeding import seed_all

    summary = seed_all(conn)
    check("reset --demo restores seeded state", summary["runs"] >= 240 and len(summary["cases"]) == 12)

    hero_id = summary["cases"].get("hero_after_hours_outage")
    check("hero case exists", bool(hero_id))

    try:
        blocked = run_gate(conn, candidate="v_regressed")
        check("gate(v_regressed) verdict is BLOCK", blocked.verdict == "BLOCK", blocked.verdict)
        check(
            "hero case is in the regression list",
            hero_id in blocked.regressed_case_ids,
            f"regressed={blocked.regressed_case_ids}",
        )
        check(
            "all verdicts served from cache (airplane-mode safe)",
            all(
                (db.get_cached_result(conn, c.eval_case_id, blocked.candidate_version_id) or {}).get(
                    "passed"
                )
                is not None
                for c in blocked.cases
            ),
        )
    except GateError as exc:
        check("gate(v_regressed) ran", False, str(exc))

    try:
        fixed = run_gate(conn, candidate="v_fixed")
        check("gate(v_fixed) verdict is PASS", fixed.verdict == "PASS", fixed.verdict)
        check("gate(v_fixed) has zero regressions", not fixed.regressed_case_ids)
        relative = run_gate(conn, candidate="v_fixed", baseline="v_regressed", persist=False)
        check(
            "v_fixed counts newly-fixed cases vs v_regressed",
            len(relative.newly_fixed_case_ids) >= 2 and relative.verdict == "PASS",
            f"newly_fixed={len(relative.newly_fixed_case_ids)} verdict={relative.verdict}",
        )
    except GateError as exc:
        check("gate(v_fixed) ran", False, str(exc))

    print("-" * 60)
    if failures:
        typer.secho(
            f"DEMO-CHECK FAILED: {len(failures)} assertion(s) failed: {', '.join(failures)}",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)
    typer.secho("DEMO-CHECK PASSED — the scripted demo path is solid.", fg=typer.colors.GREEN, bold=True)
    raise typer.Exit(code=0)


@app.command(name="install-hook")
def install_hook() -> None:
    """Install a git pre-push hook that runs `recoil gate` against the published baseline."""
    git_dir = Path(".git")
    if not git_dir.is_dir():
        typer.secho("not a git repository (run from the repo root)", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    hooks = git_dir / "hooks"
    hooks.mkdir(exist_ok=True)
    hook = hooks / "pre-push"
    hook.write_text(
        "#!/bin/sh\n"
        "# Installed by `recoil install-hook` — the publish gate is literal CI.\n"
        'echo "[recoil] running regression gate before push..."\n'
        "recoil gate --candidate v_fixed || {\n"
        '  echo "[recoil] BLOCK: push refused — fix the regression or mute the case.";\n'
        "  exit 1;\n"
        "}\n",
        encoding="utf-8",
        newline="\n",
    )
    try:
        hook.chmod(0o755)
    except OSError:
        pass
    print(f"pre-push hook installed at {hook} — pushes now run the gate for real.")


@app.command()
def doctor() -> None:
    """Print the green/red readiness checklist. Run this before going on stage."""
    from .doctor import run_doctor

    ready = run_doctor()
    raise typer.Exit(code=0 if ready else 1)


@app.command()
def sentinel(
    out: Optional[str] = typer.Option(
        None, "--out", help="Output path for cited.md (default: repo root cited.md)"
    ),
    skip_gate: bool = typer.Option(
        False, "--skip-gate", help="Skip the frozen-failure replay gate (not recommended)"
    ),
    watch: Optional[int] = typer.Option(
        None,
        "--watch",
        help="Autonomy loop: re-run every N seconds forever (Ctrl-C to stop)",
    ),
) -> None:
    """Run the autonomous intel agent: replay frozen failures (regression gate) ->
    fetch live ground truth -> generate a cited report (live model) -> verify every
    claim -> publish cited.md on PASS. Exits 1 (BLOCK) on regression or failed
    verification; cited.md stays untouched. --watch N makes it fully autonomous."""
    import time as _time

    if watch is not None:
        interval = max(watch, 60)
        print(f"recoil sentinel — autonomous loop, every {interval}s (Ctrl-C to stop)")
        while True:
            code = _sentinel_once(out=out, skip_gate=skip_gate)
            print(f"[loop] run finished with exit {code}; next run in {interval}s")
            _time.sleep(interval)
    raise typer.Exit(code=_sentinel_once(out=out, skip_gate=skip_gate))


def _sentinel_once(*, out: Optional[str], skip_gate: bool) -> int:
    """One sentinel cycle. Returns the exit code (0 PASS, 1 BLOCK, 2 error)."""
    import time as _time
    from pathlib import Path as _Path

    from .sentinel import fetch_snapshot, generate_report, publish_report, verify_report
    from .sentinel.agent import SentinelError
    from .sentinel.gate import freeze_failure, list_sentinel_cases, replay_frozen_cases
    from .sentinel.sources import SourceError

    conn = _conn()
    print("recoil sentinel — autonomous intel run (live path, no mock)")
    print("-" * 64)
    try:
        frozen = list_sentinel_cases(conn)
        if frozen and not skip_gate:
            gate_result = replay_frozen_cases(conn)
            print(
                f" [0/4] regression gate: replayed {gate_result['checked']} frozen failure(s) — "
                f"{len(gate_result['regressions'])} regression(s), "
                f"{len(gate_result['newly_fixed'])} newly fixed"
            )
            if gate_result["verdict"] == "BLOCK":
                for c in gate_result["regressions"]:
                    typer.secho(f"        x REGRESSED: {c['title']}", fg=typer.colors.RED)
                typer.secho(
                    f" {BLOCK_MARK} publish refused before generation: a previously-fixed "
                    "failure mode is back. Fix the agent, then re-run.",
                    fg=typer.colors.RED,
                    bold=True,
                )
                return 1
        elif frozen:
            print(f" [0/4] regression gate SKIPPED ({len(frozen)} frozen case(s) not replayed)")
        t0 = _time.perf_counter()
        snapshot = fetch_snapshot()
        fetch_ms = (_time.perf_counter() - t0) * 1000
        print(
            f" [1/4] ground truth: {len(snapshot['metrics'])} live metrics "
            f"(CoinGecko + DefiLlama) in {fetch_ms:.0f}ms"
        )

        report, llm_stats = generate_report(snapshot)
        print(
            f" [2/4] report generated by {llm_stats['model']}: "
            f"{len(report.findings)} findings, {llm_stats['prompt_tokens']}->"
            f"{llm_stats['completion_tokens']} tok, ${llm_stats['cost_usd']}, "
            f"{llm_stats['latency_ms']:.0f}ms"
        )

        verification = verify_report(report, snapshot)
        ok = sum(1 for c in verification.checks if c.ok)
        print(f" [3/4] verification: {ok}/{len(verification.checks)} claims grounded")
        for p in verification.problems:
            typer.secho(f"        x {p}", fg=typer.colors.RED)

        result = publish_report(
            conn,
            report=report,
            snapshot=snapshot,
            verification=verification,
            llm_stats=llm_stats,
            fetch_ms=fetch_ms,
            out_path=_Path(out) if out else None,
        )
        if result["published"]:
            typer.secho(
                f" [4/4] {PASS_MARK} published: {result['path']} (run {result['run_id'][:8]})",
                fg=typer.colors.GREEN,
                bold=True,
            )
            return 0
        case_id = freeze_failure(
            conn,
            run_id=result["run_id"],
            report=report,
            snapshot=snapshot,
            verification=verification,
        )
        typer.secho(
            f" [4/4] {BLOCK_MARK} publication REFUSED — {len(result['problems'])} claim(s) "
            f"failed ground-truth verification (run {result['run_id'][:8]}). cited.md untouched. "
            f"Failure FROZEN as regression case {case_id[:8]} — it will be replayed before "
            "every future publish.",
            fg=typer.colors.RED,
            bold=True,
        )
        return 1
    except (SourceError, SentinelError) as exc:
        typer.secho(f"sentinel error: {exc}", fg=typer.colors.RED, err=True)
        return 2


@app.command()
def serve(
    port: int = typer.Option(config.API_PORT, "--port", help="API port (pinned default 8787)"),
) -> None:
    """Start the Recoil API server (FastAPI + SSE) on the pinned port."""
    import errno

    import uvicorn

    try:
        uvicorn.run("server.main:app", host="127.0.0.1", port=port, log_level="info")
    except OSError as exc:
        if exc.errno in (errno.EADDRINUSE, 10048):
            typer.secho(
                f"port {port} is already in use — is another `recoil serve` running? "
                f"Stop it or pass --port.",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=2)
        raise


def main() -> None:  # console_scripts entry
    app()


if __name__ == "__main__":
    main()
