"""Experiment and promotion authority, separate from model proposal generation.

Trusted host code binds evaluator/checker hashes to reviewed callables. No JSON
field, model score, or externally supplied receipt is accepted as an evaluation.
Callbacks run with host privileges; isolate untrusted implementations separately.
"""
from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Callable
from .store import Store
from .types import (FoldError, Policy, Proposal, canonical, data, decode, digest,
                    exact_fields, identity, number, text, bounded_difference_summary, interaction_summary)


@dataclass(frozen=True)
class Evaluator:
    """Approved evaluator: return {loss, cost, output}, then independently check output.

    loss must be in [0,1]; lower is better. Cost units and population are in Policy.
    max_seconds is checked after each call; use a killable subprocess for hard limits.
    Code hashes bind recorded semantics only as faithfully as the host registers them.
    """
    code_hash: str
    run: Callable[[bytes, dict], dict]
    check: Callable[[dict, dict], bool]

    def __post_init__(self):
        digest("evaluator", self.code_hash)
        if not callable(self.run) or not callable(self.check):
            raise FoldError("reviewed evaluator and independent checker required")


@dataclass(frozen=True)
class Checker:
    """A trusted verifier registration, not a model-named executable.

    coverage='finite' can certify only the exact declared finite statement. A
    formal verifier may be installed by the operator, but none is shipped here.
    """
    code_hash: str
    coverage: str
    verify: Callable[[dict, bytes, tuple[dict,...]], bool]

    def __post_init__(self):
        digest("checker", self.code_hash)
        if self.coverage not in {"finite", "formal"} or not callable(self.verify):
            raise FoldError("invalid checker registration")


class Folding:
    def __init__(self, store: Store, scope: str, evaluator: Evaluator | None = None):
        self.store, self.scope, self.evaluator = store, scope, evaluator
        state = store.state(scope)
        self.policy = Policy.parse(store.json(state["policy"]))
        if evaluator is not None and evaluator.code_hash != self.policy.evaluator_hash:
            raise FoldError("evaluator differs from frozen policy")

    @classmethod
    def create(cls, store: Store, policy: Policy, champion: bytes,
               units: dict[str, list[dict]], evaluator: Evaluator | None = None):
        if not isinstance(policy, Policy):
            raise FoldError("typed policy required")
        if evaluator is not None and evaluator.code_hash != policy.evaluator_hash:
            raise FoldError("evaluator differs from frozen policy")
        exact_fields(units, {"screen", "validation", "holdout"})
        refs = {}
        for phase, values in units.items():
            minimum = getattr(policy, phase+"_units")
            if type(values) is not list or len(values) < minimum:
                raise FoldError(f"too few independent {phase} units")
            refs[phase] = []
            for value in values:
                if type(value) is not dict:
                    raise FoldError("units must be JSON objects, not unverified identifiers")
                refs[phase].append(store.put_json(value))
        allrefs = [ref for values in refs.values() for ref in values]
        if len(allrefs) != len(set(allrefs)):
            raise FoldError("duplicate content or overlapping evaluation splits")
        parent = store.put(champion)
        state = {"schema_version":1,"scope":policy.scope,"revision":0,
                 "policy":store.put_json(data(policy)),"origin":parent,"champion":parent,
                 "units":refs,"selection_closed":False,"holdout_spent":False,
                 "holdout_candidate":None,"candidates":{},"claims":{},"memory":{},
                 "admissions":{},"public": [parent], "previous_champions":[]}
        store.create(state)
        return cls(store, policy.scope, evaluator)

    @property
    def state(self):
        return self.store.state(self.scope)

    def freeze(self, proposal: Proposal) -> str:
        """Freeze a single declared mechanism. Model-authored statuses are impossible.

        A mechanism description is an operator declaration, not automatic causal
        verification that arbitrary submitted code contains only one change.
        """
        if not isinstance(proposal, Proposal):
            raise FoldError("strict typed proposal required")
        self.store.get(proposal.artifact)
        ref = self.store.put_json(data(proposal))
        def change(s):
            if s["selection_closed"] or s["holdout_spent"]:
                raise FoldError("generation is sealed for this evaluation family")
            if proposal.base != s["champion"]:
                raise FoldError("stale champion")
            if len(s["candidates"]) >= self.policy.max_candidates or ref in s["candidates"]:
                raise FoldError("candidate budget exhausted or candidate already frozen")
            if any(self.store.json(c["proposal"])["artifact"] == proposal.artifact for c in s["candidates"].values()):
                raise FoldError("renaming the same artifact is not a new candidate")
            for c in proposal.components:
                record = s["candidates"].get(c)
                if record is None or record["status"] != "screened":
                    raise FoldError("components must pass separate screens before composition")
                if self.store.json(record["proposal"])["base"] != proposal.base:
                    raise FoldError("components must share the same frozen parent")
            s["candidates"][ref] = {"proposal":ref,"status":"proposed","receipts":{}}
            s["public"] = sorted(set(s["public"]+[proposal.artifact,ref]))
            return ref, {"proposal":ref,"artifact":proposal.artifact,"base":proposal.base}
        return self.store.update(self.scope, "proposal-frozen", change)

    def _measure(self, artifact: str, unit: str) -> dict:
        if self.evaluator is None:
            raise FoldError("no trusted evaluator installed")
        case = self.store.json(unit)
        started = time.monotonic()
        try:
            raw = self.evaluator.run(self.store.get(artifact), decode(canonical(case)))
            exact_fields(raw, {"loss", "cost", "output"})
            number("loss", raw["loss"], 0, 1)
            number("cost", raw["cost"], 0, 1e18)
            canonical(raw["output"])
            ok = self.evaluator.check(decode(canonical(case)), decode(canonical(raw["output"])))
            if type(ok) is not bool:
                raise FoldError("evaluator checker returned a non-boolean")
            seconds = time.monotonic()-started
            ref = self.store.put_json({"unit":unit,"artifact":artifact,"output":raw["output"]})
            return {"loss":raw["loss"],"cost":raw["cost"],"seconds":seconds,"correct":ok,
                    "failed":not ok or seconds>self.policy.max_seconds or raw["cost"]>self.policy.max_cost,
                    "evidence":ref}
        except Exception as exc:
            return {"loss":1.0,"cost":0,"seconds":time.monotonic()-started,"correct":False,"failed":True,
                    "evidence":self.store.put_json({"unit":unit,"artifact":artifact,"error":type(exc).__name__})}

    def _reserve(self, candidate: str, phase: str):
        if self.evaluator is None:
            raise FoldError("no trusted evaluator")
        digest("candidate",candidate)
        if phase not in {"premise", "screen", "validation", "holdout", "interaction"}:
            raise FoldError("unknown evaluation phase")
        def change(s):
            c = s["candidates"].get(candidate)
            if c is None or phase in c["receipts"]:
                raise FoldError("unknown candidate or phase already attempted")
            proposal = Proposal.parse(self.store.json(c["proposal"]))
            if proposal.base != s["champion"]:
                raise FoldError("evaluation against a stale champion")
            if s["holdout_spent"]:
                raise FoldError("confirmation family is permanently sealed")
            expected = {"interaction":"proposed","premise":"proposed","screen":"premise-passed","validation":"screened","holdout":"validated"}[phase]
            if c["status"] != expected:
                raise FoldError("evaluation stages may not be skipped or repeated")
            if phase in {"premise", "screen", "interaction"} and s["selection_closed"]:
                raise FoldError("development is sealed")
            if phase == "interaction" and not proposal.components:
                raise FoldError("factorial check requires two screened components")
            if phase in {"premise", "screen"} and proposal.components:
                prior = c["receipts"].get("interaction")
                if not prior or prior.get("status") != "passed":
                    raise FoldError("combination requires a completed four-arm interaction check")
            if phase == "validation":
                # All candidates must now remain frozen. Validation outcomes may
                # select among them but cannot generate a new hypothesis family.
                s["selection_closed"] = True
            if phase == "holdout":
                s["selection_closed"] = True
                s["holdout_spent"] = True  # durable reservation BEFORE any outcome
                s["holdout_candidate"] = candidate
            c["receipts"][phase] = {"status":"reserved", "ref":None}
            return proposal, {"proposal":candidate,"phase":phase,"outcomes_observed":False}
        return self.store.update(self.scope,"evaluation-reserved",change)

    def evaluate(self, candidate: str, phase: str) -> dict:
        """Run real paired work. A crashed reservation cannot be silently rerun."""
        proposal = self._reserve(candidate, phase)
        s = self.state
        refs = s["units"]["screen" if phase in {"premise", "interaction"} else phase]
        if phase == "premise":
            refs = refs[:self.policy.premise_units]
        try:
            if phase == "interaction":
                comps = [Proposal.parse(self.store.json(s["candidates"][c]["proposal"])) for c in proposal.components]
                arms = [proposal.base,comps[0].artifact,comps[1].artifact,proposal.artifact]
                four = [{"unit":u,"arms":[self._measure(a,u) for a in arms]} for u in refs]
                summary = interaction_summary(four, self.policy)
                evidence = four
                passed = summary["failures"] == 0 and summary["all_arm_failures"] == 0 and summary["mean_delta"] < -self.policy.min_effect
            else:
                rows=[]
                for index,u in enumerate(refs):
                    # Alternate order to avoid always timing one arm after the other.
                    if index % 2:
                        child=self._measure(proposal.artifact,u); base=self._measure(proposal.base,u)
                    else:
                        base=self._measure(proposal.base,u); child=self._measure(proposal.artifact,u)
                    rows.append({"unit":u,"base":base,"child":child})
                summary=bounded_difference_summary(rows,self.policy)
                evidence=rows
                threshold = summary["mean_delta"] if phase in {"premise", "screen"} else summary["upper_bound"]
                passed=summary["failures"] == 0 and (threshold <= 0 if phase == "premise" else threshold < -self.policy.min_effect)
            receipt={"schema_version":1,"scope":self.scope,"policy":s["policy"],"candidate":candidate,
                     "base":proposal.base,"artifact":proposal.artifact,"evaluator":self.policy.evaluator_hash,
                     "phase":phase,"unit_manifest":identity(refs),"measurements":evidence,
                     "summary":summary,"passed":passed,"evidence_kind":"empirical"}
            ref=self.store.put_json(receipt)
            def change(current):
                c=current["candidates"][candidate]
                if c["receipts"][phase]["status"] != "reserved":
                    raise FoldError("evaluation reservation was changed")
                c["receipts"][phase]={"status":"passed" if passed else "failed","ref":ref}
                if phase != "interaction" or not passed:
                    c["status"] = {"premise":"premise-passed","screen":"screened","validation":"validated","holdout":"ready"}.get(phase,"proposed") if passed else "killed"
                # Only development-derived measurements may be summarized for a proposer.
                return receipt, {"proposal":candidate,"phase":phase,"receipt":ref}
            return self.store.update(self.scope,"evaluation-completed",change)
        except BaseException:
            # A consumed holdout stays consumed, including KeyboardInterrupt.
            def failed(current):
                c=current["candidates"][candidate]
                if c["receipts"][phase]["status"] == "reserved":
                    c["receipts"][phase]["status"]="aborted"
                    c["status"]="killed"
                return None,{"proposal":candidate,"phase":phase}
            self.store.update(self.scope,"evaluation-aborted",failed)
            raise

    def promote(self, candidate: str) -> str:
        """Atomic compare-and-swap. Receipts are fetched/recomputed, not imported."""
        def change(s):
            c=s["candidates"].get(candidate)
            if c is None or c["status"] != "ready" or s["holdout_candidate"] != candidate:
                raise FoldError("candidate is not eligible for promotion")
            p=Proposal.parse(self.store.json(c["proposal"]))
            if p.base != s["champion"]:
                raise FoldError("champion changed after evaluation")
            self.store.get(p.artifact); self.store.get(p.base)
            for phase in ("premise","screen","validation","holdout"):
                slot=c["receipts"].get(phase)
                if not slot or slot["status"]!="passed":
                    raise FoldError("missing evaluation stage")
                r=self.store.json(slot["ref"])
                expected_units=s["units"]["screen"][:self.policy.premise_units] if phase=="premise" else s["units"][phase]
                if any(r[k]!=v for k,v in {"scope":self.scope,"candidate":candidate,"base":p.base,
                       "artifact":p.artifact,"phase":phase,"policy":s["policy"],"evaluator":self.policy.evaluator_hash,
                       "unit_manifest":identity(expected_units),"evidence_kind":"empirical"}.items()):
                    raise FoldError("receipt scope/artifact/evaluator mismatch")
                if [m["unit"] for m in r["measurements"]] != expected_units:
                    raise FoldError("incomplete or mismatched unit pairing")
                summary=bounded_difference_summary(r["measurements"],self.policy)
                if summary!=r["summary"] or summary["failures"] or type(r["passed"])is not bool or not r["passed"]:
                    raise FoldError("invalid measurements or receipt summary")
                stat=summary["mean_delta"] if phase in {"premise","screen"} else summary["upper_bound"]
                if not (stat <= 0 if phase=="premise" else stat < -self.policy.min_effect):
                    raise FoldError("recomputed promotion gate failed")
                for row in r["measurements"]:
                    for side, artifact in (("base",p.base),("child",p.artifact)):
                        ev=self.store.json(row[side]["evidence"])
                        if ev["unit"]!=row["unit"] or ev["artifact"]!=artifact:
                            raise FoldError("measurement artifact binding failed")
            if p.components:
                slot=c["receipts"].get("interaction")
                if not slot or slot["status"]!="passed":
                    raise FoldError("composition interaction receipt missing")
                r=self.store.json(slot["ref"])
                expected_units=s["units"]["screen"]
                bindings={"scope":self.scope,"policy":s["policy"],"candidate":candidate,
                          "base":p.base,"artifact":p.artifact,"evaluator":self.policy.evaluator_hash,
                          "phase":"interaction","unit_manifest":identity(expected_units),"evidence_kind":"empirical"}
                if any(r[k]!=v for k,v in bindings.items()) or type(r["passed"]) is not bool or not r["passed"]:
                    raise FoldError("invalid factorial receipt bindings")
                summary=interaction_summary(r["measurements"],self.policy)
                if summary!=r["summary"] or summary["all_arm_failures"] or summary["mean_delta"] >= -self.policy.min_effect:
                    raise FoldError("factorial evidence did not pass on recomputation")
                if [row["unit"] for row in r["measurements"]] != expected_units:
                    raise FoldError("factorial units differ from preregistration")
                arms=[p.base]+[Proposal.parse(self.store.json(s["candidates"][ref]["proposal"])).artifact for ref in p.components]+[p.artifact]
                for row in r["measurements"]:
                    for measurement,artifact in zip(row["arms"],arms):
                        evidence=self.store.json(measurement["evidence"])
                        if evidence["unit"]!=row["unit"] or evidence["artifact"]!=artifact:
                            raise FoldError("factorial artifact binding failed")
            s["previous_champions"].append(s["champion"])
            s["champion"]=p.artifact
            c["status"]="promoted"
            # No results or feedback are released into an active generation loop.
            admission={"kind":"empirical-promotion","scope":self.scope,"candidate":candidate,
                       "artifact":p.artifact,"prior":p.base,"policy":s["policy"],
                       "claim":"Improvement passed the declared metric/population gates; no theorem established."}
            a=self.store.put_json(admission);s["admissions"][a]=admission
            return a,{"admission":a,"old":p.base,"new":p.artifact}
        return self.store.update(self.scope,"champion-promoted",change)

    def admit_claim(self, statement: dict, evidence: bytes, checker: Checker,
                    *, dependencies: tuple[str,...]=()) -> str:
        """Claims use registered proof/finite checkers, never statistical receipts.

        Statement coverage must match its registered verifier. The verifier is
        responsible for binding every statement field to the actual evidence.
        """
        exact_fields(statement,{"name","coverage","statement","domain"})
        text("claim name",statement["name"],150)
        text("statement",statement["statement"],20000)
        text("domain",statement["domain"],2000)
        if not isinstance(checker,Checker) or statement["coverage"]!=checker.coverage:
            raise FoldError("finite/statistical evidence cannot be promoted into a formal theorem")
        if type(dependencies) is not tuple or any(type(r)is not str for r in dependencies) or len(dependencies)!=len(set(dependencies)):
            raise FoldError("invalid claim dependencies")
        s=self.state; dep=[]
        for ref in dependencies:
            if ref not in s["claims"]:
                raise FoldError("unknown or cross-scope claim dependency")
            value=self.store.json(ref)
            if checker.coverage=="formal" and value["coverage"]!="formal":
                raise FoldError("a finite test cannot serve as a general formal premise")
            dep.append(value)
        source=self.store.put(evidence)
        subject=self.store.put_json(statement)
        try:
            ok=checker.verify(decode(canonical(statement)),bytes(evidence),tuple(dep))
        except Exception as exc:
            raise FoldError("claim verifier failed closed") from exc
        if type(ok) is not bool or not ok:
            raise FoldError("claim verifier rejected the exact statement/evidence")
        receipt={"kind":"claim","scope":self.scope,"subject":subject,"evidence":source,
                 "checker":checker.code_hash,"coverage":checker.coverage,"dependencies":list(dependencies)}
        ref=self.store.put_json(receipt)
        def change(current):
            if ref in current["claims"]:
                raise FoldError("claim already admitted")
            current["claims"][ref]=receipt
            admission={"kind":"checked-"+checker.coverage,"scope":self.scope,"claim_ref":ref,
                       "statement":statement["statement"],"domain":statement["domain"]}
            a=self.store.put_json(admission);current["admissions"][a]=admission
            return a,{"claim":ref,"admission":a}
        return self.store.update(self.scope,"claim-checked",change)

    def remember(self, candidate: str, *, summary: str, preserved: str, next_test: str) -> str:
        """Trusted memory-writer operation: development-only, source-bound summaries.

        These texts are operator-authored advisory summaries, not proof authority.
        No validation/holdout receipt or free-form result object enters this channel.
        """
        for name,value in (("summary",summary),("preserved",preserved),("next_test",next_test)):
            text(name,value,1200)
        def change(s):
            if s["selection_closed"] or s["holdout_spent"]:
                raise FoldError("no generation-facing memory writes after confirmation starts")
            c=s["candidates"].get(candidate)
            r=c and (c["receipts"].get("screen") or c["receipts"].get("premise"))
            if not r or r["status"] not in {"passed","failed"}:
                raise FoldError("memory requires an executed development receipt")
            m={"scope":self.scope,"source":r["ref"],"candidate":candidate,
               "summary":summary,"preserved":preserved,"next_test":next_test,
               "authority":"advisory-development-summary; not evidence or a family-wide impossibility"}
            ref=self.store.put_json(m);s["memory"][ref]=m
            return ref,{"memory":ref,"source":r["ref"]}
        return self.store.update(self.scope,"memory-written",change)

    def admission(self, ref: str) -> dict:
        s=self.state
        if ref not in s["admissions"] or self.store.json(ref)!=s["admissions"][ref]:
            raise FoldError("unknown, forged or cross-campaign admission")
        return self.store.json(ref)

    def rollback(self, reason: str) -> str:
        """Trusted operator rollback. Historical receipts remain; holdout stays spent."""
        text("rollback reason", reason, 2000)
        def change(s):
            if not s["previous_champions"]:
                raise FoldError("no previous promoted champion to restore")
            old=s["champion"]
            prior=s["previous_champions"].pop()
            self.store.get(prior)
            for candidate in s["candidates"].values():
                if candidate["status"]=="promoted":
                    candidate["status"]="rolled-back"
            s["champion"]=prior
            s["selection_closed"]=True
            admission={"kind":"operator-rollback","scope":self.scope,"old":old,
                       "restored":prior,"reason":reason,
                       "claim":"Operational rollback only; prior evaluations remain historical records."}
            ref=self.store.put_json(admission)
            s["admissions"][ref]=admission
            return ref,{"admission":ref,"old":old,"restored":prior}
        return self.store.update(self.scope,"champion-rolled-back",change)
