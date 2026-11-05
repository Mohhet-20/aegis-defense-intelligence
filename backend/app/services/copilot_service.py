"""Evidence-grounded copilot.

Retrieval always happens BEFORE any generation. Without a configured model the
copilot is still fully functional but strictly extractive/deterministic:
answers are verbatim, cited excerpts and summaries assembled from stored
fields. Every claim carries a `kind` so the UI can separate:

  source_statement  verbatim text from a record (quote is attached)
  record_summary    assembled by this application from stored fields (no model)
  generated_summary written by a language model; only present in generative mode
  system_note       a limitation / notice from the application

Conflicts are listed side by side and never resolved. Nothing here claims a
source is reliable, that an action occurred, or that a keyword score means a
statement is true."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import AuthenticatedUser
from app.models.assessment import AssessmentEvidenceLink
from app.models.evidence_relationship import EvidenceRelationship
from app.models.investigation_workspace import InvestigationLink, InvestigationNote
from app.retrieval import providers
from app.retrieval.lexical import excerpt, query_terms, support_ratio, tokenize
from app.services import (
    investigation_links_service as links, investigation_search_service as inv_search, investigation_service,
    investigation_timeline_service as timeline_svc, retrieval_citation_service as cites, retrieval_search_service as search_svc,
    retrieval_sources as src,
)
from app.services.timeutil import iso
from app.services.workspace_errors import invalid, not_found

log = logging.getLogger("aegis.copilot")
settings = get_settings()

TASKS = ("question", "summarize_investigation", "chronology", "compare", "report_draft", "related")
CLAIM_KINDS = ("source_statement", "record_summary", "generated_summary", "system_note")
_INJECTION = re.compile(
    r"(ignore (all |any |the )?(previous|prior|above) (instructions|rules)|disregard (the )?(system|previous)|"
    r"you are now|system prompt|reveal (your|the) (secret|key|password)|grant (me|yourself) (admin|access)|act as (an? )?(admin|administrator))", re.I)
STANDING_NOTICE = ("Results are assembled from stored records. Appearing in results does not mean a source is reliable, "
                   "and keyword matching does not establish that a statement is true.")


SIMULATION_NOTICE = ("Some cited records are SIMULATED scenarios on synthetic data. Their content is hypothetical: "
                     "it describes what a model produced under stated assumptions, not what was observed, and it is not evidence.")


class Builder:
    def __init__(self, task: str):
        self.task = task
        self.mode = "extractive" if task == "question" else "deterministic"
        self.status = "answered"
        self.claims: list[dict] = []
        self.citations: list[dict] = []
        self.uncertainty: list[str] = [STANDING_NOTICE]
        self.missing: list[str] = []
        self.conflicts: list[dict] = []
        self.followups: list[str] = []
        self.retrieval: dict = {}
        self.extra: dict = {}
        self._cit_index: dict[tuple, str] = {}
        self.generative_notice: Optional[str] = None

    def cite(self, c: Optional[dict]) -> Optional[str]:
        if c is None:
            return None
        key = (c["record_type"], c["record_id"], c.get("quote"))
        if key not in self._cit_index:
            cid = f"c{len(self.citations) + 1}"
            self._cit_index[key] = cid
            self.citations.append(dict(c, id=cid))
        return self._cit_index[key]

    def claim(self, text: str, kind: str, cit_ids: Optional[list[Optional[str]]] = None, support: Optional[str] = None,
              ratio: Optional[float] = None) -> dict:
        assert kind in CLAIM_KINDS
        ids = [i for i in (cit_ids or []) if i]
        c = {"id": f"k{len(self.claims) + 1}", "text": text, "kind": kind, "citation_ids": ids,
             "support": support or ("verbatim_quote" if kind == "source_statement" else ("record_fields" if kind == "record_summary" else None)),
             "support_ratio": ratio}
        self.claims.append(c)
        return c

    def to_dict(self, db: Session, user: AuthenticatedUser) -> dict:
        avail, pname, reason = providers.provider_available()
        if any(c["record_type"] == "scenario" for c in self.citations):
            self.uncertainty.append(SIMULATION_NOTICE)
        used = {}
        for c in self.citations:
            used[(c["record_type"], c["record_id"])] = {"record_type": c["record_type"], "record_id": c["record_id"], "title": c.get("title"), "link": c.get("link")}
        return {
            "task": self.task, "mode": self.mode, "status": self.status,
            "generation": {"available": avail, "provider": pname, "reason": reason, "notice": self.generative_notice},
            "claims": self.claims, "citations": self.citations, "uncertainty": self.uncertainty,
            "missing_information": self.missing, "conflicts": self.conflicts, "followups": self.followups,
            "records_used": list(used.values()), "retrieval": self.retrieval, **self.extra,
            "generated_at": iso(datetime.now(timezone.utc)),
        }


# ---------------------------------------------------------------- question

def _hit_citation(h: dict) -> dict:
    return cites.base(h["record_type"], h["record_id"], document_version=h["document_version"], chunk_position=h["chunk_position"],
                      title=h["title"], section=h["section"], quote=h["excerpt"], source_time=h["source_time"], link=h["link"])


def answer_question(db: Session, user: AuthenticatedUser, question: str, *, investigation_id: Optional[str] = None,
                    record_types: Optional[list[str]] = None) -> dict:
    q = (question or "").strip()
    if not q:
        raise invalid("question must not be empty")
    if len(q) > settings.COPILOT_MAX_QUESTION_CHARS:
        raise invalid(f"question must be at most {settings.COPILOT_MAX_QUESTION_CHARS} characters")
    b = Builder("question")
    res = search_svc.search(db, user, q[: settings.RETRIEVAL_MAX_QUERY_CHARS],
                            filters=search_svc.SearchFilters(record_types=record_types, investigation_id=investigation_id),
                            page=1, page_size=settings.COPILOT_CONTEXT_CHUNKS, include_text=True)
    terms = res.terms
    b.retrieval = {"query_terms": terms, "records_considered": res.total, "method": "bm25_keyword", "semantic_used": False,
                   "candidates_truncated": res.truncated, "scoped_to_investigation": investigation_id}
    supporting = [h for h in res.items if terms and len(h["matched_terms"]) / len(terms) >= 0.5]
    weak = [h for h in res.items if h not in supporting]
    b.retrieval["weak_matches"] = [{"record_type": h["record_type"], "record_id": h["record_id"], "title": h["title"],
                                    "matched_terms": h["matched_terms"], "link": h["link"]} for h in weak[:5]]
    if not supporting:
        b.status = "no_relevant_records" if not res.items else "insufficient"
        b.claim("The records available to you do not answer this question." if not res.items else
                "The records available to you only partly match this question, so it is not answered.", "system_note")
        b.missing.append("No record you can access contains the key terms of this question." if not res.items else
                         "Only some of the question's terms appear in your accessible records.")
        b.followups = ["Try different or fewer keywords.", "Ask for the indexing status if records may be missing from the index."]
        if res.notice:
            b.uncertainty.append(res.notice)
        return b.to_dict(db, user)

    inj = 0
    stale = []
    src_blocks = []
    for n, h in enumerate(supporting[: settings.COPILOT_CONTEXT_CHUNKS], 1):
        cid = b.cite(_hit_citation(h))
        b.claim(h["excerpt"], "source_statement", [cid])
        if _INJECTION.search(h.get("text") or h["excerpt"]):
            inj += 1
        if h["stale"]:
            stale.append(h["title"] or h["record_id"])
        src_blocks.append({"id": f"S{n}", "record_type": h["record_type"], "source_time": h["source_time"],
                           "quote": h.get("text") or h["excerpt"], "cit": cid, "hit": h})
    if inj:
        b.uncertainty.append(f"{inj} retrieved record(s) contain text that resembles instructions. It was treated purely as record content and had no effect on this answer.")
    if stale:
        b.uncertainty.append("These records changed after they were indexed, so excerpts may be out of date: " + ", ".join(stale[:5]) + ".")
    if any(not h["content_available"] for h in supporting):
        b.uncertainty.append("Some matches are metadata-only (e.g. media filenames); their content has not been read.")
    b.uncertainty.append("Dates shown are the record's own timestamps; where a record has none, none is implied.")

    avail, pname, reason = providers.provider_available()
    if not avail:
        b.generative_notice = f"Generative answers are unavailable: {reason} Showing source excerpts only."
    else:
        try:
            raw = providers.get_generation_provider().generate(
                providers.SYSTEM_PROMPT, providers.build_user_prompt(q, src_blocks), max_tokens=settings.COPILOT_MAX_OUTPUT_TOKENS)
            parsed = providers.parse_model_answer(raw)
        except (providers.ProviderError, providers.ProviderUnavailable) as exc:
            b.generative_notice = f"The generation provider did not produce a usable answer ({exc}). Showing source excerpts only."
            log.warning("copilot generation unavailable: %s", type(exc).__name__)
        else:
            by_id = {s["id"]: s for s in src_blocks}
            gen: list[dict] = []
            for mc in parsed.claims:
                good = [i for i in mc.citation_ids if i in by_id]
                bad = [i for i in mc.citation_ids if i not in by_id]
                ids = [by_id[i]["cit"] for i in good]
                if bad:
                    support, ratio = "unverified", None
                    b.uncertainty.append(f"A generated statement cited a source that was not retrieved ({', '.join(bad[:3])}); that citation was discarded.")
                elif not good:
                    support, ratio = "none", None
                    b.uncertainty.append("A generated statement has no source citation and should be treated as unsupported commentary.")
                else:
                    ratio = round(support_ratio(mc.text, [by_id[i]["quote"] for i in good]), 2)
                    support = "lexical_overlap" if ratio >= 0.5 else "weak_overlap"
                    if support == "weak_overlap":
                        b.uncertainty.append("A generated statement has little wording in common with its cited source; verify it against the cited record.")
                gen.append((mc.text, ids, support, ratio))
            b.mode = "generative"
            existing = b.claims
            b.claims = []
            for text, ids, support, ratio in gen:
                b.claim(text, "generated_summary", ids, support, ratio)
            for c in existing:  # source excerpts remain visible and distinct
                c["id"] = f"k{len(b.claims) + 1}"
                b.claims.append(c)
            b.uncertainty.extend(parsed.uncertainty[:10])
            b.followups = [f[:200] for f in parsed.followups[:5]]
            b.uncertainty.append("Statements marked generated_summary were written by a language model; "
                                 "lexical overlap with the cited text is a rough check, not proof the statement is supported.")
    if not b.followups:
        b.followups = ["Open a cited record to read the full source.", "Narrow the question to one investigation to reduce noise."]
    return b.to_dict(db, user)


# ---------------------------------------------------------- investigation

def _visible_records(db: Session, user: AuthenticatedUser, inv) -> tuple[list[tuple[str, str, object]], int]:
    vis, other = [], 0
    for r in links.effective_records(db, inv):
        row = r["row"]
        if row is None:
            continue
        if r["record_type"] not in src.MODELS:
            other += 1
            continue
        if src.can_view(db, user, r["record_type"], row):
            vis.append((r["record_type"], r["record_id"], row))
    return vis, other


def _relationship_conflicts(db: Session, user: AuthenticatedUser, b: Builder, inv) -> None:
    rel = inv_search.relationships(db, inv)
    for it in rel["items"]:
        if it["relationship_type"] != "contradicts" or it["review_status"] == "rejected":
            continue
        left = cites.make_citation(db, user, it["source"]["record_type"], it["source"]["record_id"])
        right = cites.make_citation(db, user, it["target"]["record_type"], it["target"]["record_id"])
        if left is None or right is None:
            continue  # never reveal a conflict involving a record the user cannot read
        b.conflicts.append({
            "description": it["explanation"], "left_citation_ids": [b.cite(left)], "right_citation_ids": [b.cite(right)],
            "basis": f"{it['origin_label']}; review status: {it['review_status']}. Shown as recorded; not resolved.", "resolved": False})


def _assessment_conflicts(db: Session, user: AuthenticatedUser, b: Builder, assessments: list) -> None:
    for a in assessments:
        rows = db.execute(select(AssessmentEvidenceLink).where(
            AssessmentEvidenceLink.assessment_id == a.id, AssessmentEvidenceLink.role == "contradicting")).scalars().all()
        for l in rows:
            rtype, rid = ("event", l.event_id) if l.event_id else ("evidence", l.evidence_id)
            if not rid:
                continue
            ac, rc = cites.make_citation(db, user, "assessment", a.id), cites.make_citation(db, user, rtype, rid)
            if ac is None or rc is None:
                continue
            b.conflicts.append({
                "description": f"Assessment '{a.title}' lists this record as contradicting evidence.",
                "left_citation_ids": [b.cite(ac)], "right_citation_ids": [b.cite(rc)],
                "basis": "Recorded on the assessment's evidence links. Shown as recorded; not resolved.", "resolved": False})


def summarize_investigation(db: Session, user: AuthenticatedUser, investigation_id: str) -> dict:
    inv = investigation_service.get_accessible(db, user, investigation_id)
    if not src.has_read(user, "investigation"):
        raise not_found("Investigation")
    b = Builder("summarize_investigation")
    ic = b.cite(cites.make_citation(db, user, "investigation", inv.id))
    b.claim(f"Investigation \"{inv.title}\": status {inv.status}, priority {inv.priority}, review status {inv.review_status}. "
            f"Created {iso(inv.created_at)}.", "record_summary", [ic])
    if inv.description:
        b.claim(excerpt(inv.description, [], 400), "source_statement", [ic])
    vis, other = _visible_records(db, user, inv)
    counts: dict[str, int] = {}
    for t, _, _ in vis:
        counts[t] = counts.get(t, 0) + 1
    b.claim("Linked records you can access: " + (", ".join(f"{n} {t.replace('_', ' ')}" for t, n in sorted(counts.items())) or "none")
            + (f". {other} additional linked record(s) are of types not covered by retrieval (sensor, detection, track)." if other else ".")
            + " Records you cannot access are omitted and not counted.", "record_summary")
    notes = [n for n in db.execute(select(InvestigationNote).where(InvestigationNote.investigation_id == inv.id)
                                   .order_by(InvestigationNote.created_at.desc()).limit(50)).scalars().all()
             if src.can_view(db, user, "investigation_note", n)]
    for n in notes[:3]:
        b.claim(excerpt(n.body, [], 300), "source_statement", [b.cite(cites.make_citation(db, user, "investigation_note", n.id))])
    if not notes:
        b.missing.append("No analyst notes have been recorded on this investigation.")
    assessments = [row for t, _, row in vis if t == "assessment"]
    for a in assessments:
        ac = b.cite(cites.make_citation(db, user, "assessment", a.id))
        b.claim(f"Assessment \"{a.title}\": status {a.status}, version {a.version}"
                + (f", stated confidence {a.confidence_level}" if a.confidence_level else ", no confidence level recorded")
                + f". Question: {a.question}", "record_summary", [ac])
        for gap in (a.information_gaps or [])[:5]:
            b.missing.append(f"Information gap recorded on assessment \"{a.title}\": {gap}")
    ev = [row for t, _, row in vis if t == "evidence"]
    unreviewed = [e for e in ev if e.review_status in ("unreviewed", "needs_review")]
    if ev:
        b.claim(f"{len(ev)} evidence item(s) are linked; {len(unreviewed)} not yet reviewed. Review status is recorded per item and does not rate reliability.", "record_summary")
    if unreviewed:
        b.missing.append(f"{len(unreviewed)} linked evidence item(s) have not been reviewed.")
    legacy = links.unresolved_legacy_refs(db, inv)
    if legacy:
        b.missing.append(f"{len(legacy)} legacy record reference(s) on this investigation could not be resolved.")
    _relationship_conflicts(db, user, b, inv)
    _assessment_conflicts(db, user, b, assessments)
    if b.conflicts:
        b.uncertainty.append(f"{len(b.conflicts)} conflicting pairing(s) are recorded. They are listed side by side and have not been resolved.")
    b.uncertainty.append("Summary is assembled from stored fields by the application, not written by a model.")
    b.retrieval = {"method": "investigation_records", "records_considered": len(vis)}
    b.followups = ["Ask for a chronological overview.", "Open the conflicting records to compare them side by side."]
    return b.to_dict(db, user)


def chronology(db: Session, user: AuthenticatedUser, investigation_id: str, *, limit: int = 60) -> dict:
    inv = investigation_service.get_accessible(db, user, investigation_id)
    b = Builder("chronology")
    entries = timeline_svc.sort_entries(timeline_svc.build_entries(db, inv))
    shown, unknown, cache = 0, 0, {}
    for e in entries:
        rt, rid = e["record_type"], e["record_id"]
        cit = None
        if rt in src.MODELS:
            if (rt, rid) not in cache:
                cache[(rt, rid)] = cites.make_citation(db, user, rt, rid)
            cit = cache[(rt, rid)]
            if cit is None:
                continue  # not visible: omitted entirely
        if shown >= limit:
            b.extra["truncated"] = True
            break
        shown += 1
        label = e["time_kind"].replace("_", " ")
        when = e["timestamp"] if e["time_known"] else "time not recorded"
        if not e["time_known"]:
            unknown += 1
        txt = f"{when} — {label}: {e['title']}"
        if e.get("assumed_utc"):
            txt += " (timezone not recorded; UTC assumed)"
        b.claim(txt, "record_summary", [b.cite(cit) if cit else None])
    b.extra.setdefault("truncated", False)
    if unknown:
        b.missing.append(f"{unknown} entr{'y has' if unknown == 1 else 'ies have'} no recorded time and appear last.")
    b.uncertainty.append("Different entries use different kinds of time (event time, ingestion time, association time, processing time). "
                         "Ingestion and association times are not when the underlying event happened.")
    if not shown:
        b.status = "no_relevant_records"
        b.claim("No dated or linked records are available for a chronology.", "system_note")
    b.retrieval = {"method": "investigation_timeline", "records_considered": shown}
    return b.to_dict(db, user)


# ----------------------------------------------------------------- compare

def _pair_relationships(db: Session, refs: list[tuple[str, str]]) -> list[EvidenceRelationship]:
    ev = {i for t, i in refs if t == "event"}
    ei = {i for t, i in refs if t == "evidence"}
    if not ev and not ei:
        return []
    cond = or_(EvidenceRelationship.source_event_id.in_(ev), EvidenceRelationship.target_event_id.in_(ev),
               EvidenceRelationship.source_evidence_id.in_(ei), EvidenceRelationship.target_evidence_id.in_(ei))
    rows = db.execute(select(EvidenceRelationship).where(EvidenceRelationship.is_reversed.is_(False), cond).limit(200)).scalars().all()
    ids = set(refs)
    out = []
    for r in rows:
        s = ("event", r.source_event_id) if r.source_event_id else ("evidence", r.source_evidence_id)
        t = ("event", r.target_event_id) if r.target_event_id else ("evidence", r.target_evidence_id)
        if s in ids and t in ids:
            out.append(r)
    return out


def compare_records(db: Session, user: AuthenticatedUser, refs: list[tuple[str, str]]) -> dict:
    uniq = list(dict.fromkeys(refs))
    if not (2 <= len(uniq) <= 6):
        raise invalid("Provide between 2 and 6 distinct records to compare")
    b = Builder("compare")
    items, texts = [], {}
    for rt, rid in uniq:
        if rt not in src.MODELS:
            raise invalid(f"record_type must be one of {tuple(src.MODELS)}")
        live = src.load_live(db, user.organization_id, rt, rid)
        if live is None or not src.can_view(db, user, rt, live):
            b.missing.append("One requested record could not be loaded (it may not exist or you may not have access).")
            continue
        spec = src.build_doc(db, rt, live)
        body = cites._body(spec.text)
        c = cites.make_citation(db, user, rt, rid, quote=excerpt(body, [], 600) or None)
        cid = b.cite(c)
        texts[(rt, rid)] = body
        items.append({"citation_id": cid, "record_type": rt, "record_id": rid, "title": spec.title, "source_time": iso(spec.source_time) if spec.source_time else None,
                      "source_id": spec.source_id, "review_status": spec.review_status, "text": excerpt(body, [], 600), "link": c["link"]})
        b.claim(f"{spec.title} ({rt.replace('_', ' ')}"
                + (f", {iso(spec.source_time)}" if spec.source_time else ", no time recorded") + ")", "record_summary", [cid])
    b.extra["side_by_side"] = items
    if len(items) < 2:
        b.status = "insufficient"
        b.claim("Fewer than two of the requested records could be loaded, so there is nothing to compare.", "system_note")
        return b.to_dict(db, user)
    present = [(i["record_type"], i["record_id"]) for i in items]
    cid_of = {(i["record_type"], i["record_id"]): i["citation_id"] for i in items}
    for r in _pair_relationships(db, present):
        s = ("event", r.source_event_id) if r.source_event_id else ("evidence", r.source_evidence_id)
        t = ("event", r.target_event_id) if r.target_event_id else ("evidence", r.target_evidence_id)
        if r.relationship_type == "contradicts" and r.review_status != "rejected":
            b.conflicts.append({"description": r.explanation, "left_citation_ids": [cid_of[s]], "right_citation_ids": [cid_of[t]],
                                "basis": f"Recorded relationship ({r.origin}); review status: {r.review_status}. Not resolved.", "resolved": False})
        else:
            b.claim(f"A '{r.relationship_type}' relationship is recorded between two of these records (review status: {r.review_status}).",
                    "record_summary", [cid_of[s], cid_of[t]])
    diffs = []
    if len({i["source_id"] for i in items}) > 1:
        diffs.append("The records come from different sources.")
    if len({i["review_status"] for i in items}) > 1:
        diffs.append("The records have different review statuses.")
    times = [i["source_time"] for i in items if i["source_time"]]
    if len(times) < len(items):
        diffs.append("At least one record has no recorded time, so ordering them in time is not possible.")
    elif len(set(times)) > 1:
        diffs.append(f"Record times differ (earliest {min(times)}, latest {max(times)}).")
    toks = [set(tokenize(texts[k])) for k in present]
    common = sorted(set.intersection(*toks))[:10]
    b.extra["differences"] = diffs
    b.extra["shared_terms"] = common
    b.uncertainty.append("Shared terms show wording overlap only. They do not mean the records agree, and differences do not mean they disagree.")
    b.uncertainty.append("This comparison does not judge which record is correct.")
    b.retrieval = {"method": "side_by_side", "records_considered": len(items)}
    return b.to_dict(db, user)


# -------------------------------------------------------------- report draft

def report_draft(db: Session, user: AuthenticatedUser, investigation_id: str, *, title: Optional[str] = None) -> dict:
    inv = investigation_service.get_accessible(db, user, investigation_id)
    summ = summarize_investigation(db, user, investigation_id)
    chron = chronology(db, user, investigation_id, limit=40)
    b = Builder("report_draft")
    nums: dict[tuple, int] = {}
    remap: dict[tuple, str] = {}

    def mark(src_ans: dict, cids: list[str]) -> str:
        by = {c["id"]: c for c in src_ans["citations"]}
        out = []
        for cid in cids:
            c = by.get(cid)
            if c is None:
                continue
            k = (c["record_type"], c["record_id"], c.get("quote"))
            if k not in nums:
                nums[k] = len(nums) + 1
            remap[(id(src_ans), cid)] = b.cite(c)
            out.append(f"[{nums[k]}]")
        return " ".join(out)

    lines = [f"# {title or 'Draft report'}: {inv.title}", "",
             f"> DRAFT assembled by the application from stored records on {iso(datetime.now(timezone.utc))}. It is not reviewed, "
             "not a finding, and not model-generated. Edit before use. Bracketed numbers refer to the source list.", "", "## Overview"]
    for c in summ["claims"][:8]:
        tag = "Quoted from record" if c["kind"] == "source_statement" else "Record summary"
        lines.append(f"- {c['text']} ({tag}) {mark(summ, c['citation_ids'])}".rstrip())
    lines += ["", "## Chronology"]
    for c in chron["claims"]:
        lines.append(f"- {c['text']} {mark(chron, c['citation_ids'])}".rstrip())
    lines += ["", "## Conflicting information (not resolved)"]
    if summ["conflicts"]:
        for cf in summ["conflicts"]:
            lines.append(f"- {cf['description']} Sources: {mark(summ, cf['left_citation_ids'])} vs {mark(summ, cf['right_citation_ids'])}. {cf['basis']}")
    else:
        lines.append("- No conflicting records are recorded for this investigation.")
    lines += ["", "## Missing or unreviewed information"]
    lines += [f"- {m}" for m in (summ["missing_information"] + chron["missing_information"])] or ["- None recorded."]
    lines += ["", "## Limitations", "- Only records the author could access were used; others are omitted without being counted.",
              "- Times shown are each record's own timestamps; ingestion/association times are not event times.",
              "- A record appearing here does not imply it is reliable.", "", "## Sources"]
    by_num = sorted(nums.items(), key=lambda kv: kv[1])
    cit_by_key = {(c["record_type"], c["record_id"], c.get("quote")): c for c in b.citations}
    for k, n in by_num:
        c = cit_by_key[k]
        lines.append(f"[{n}] {c.get('title') or c['record_id']} ({c['record_type'].replace('_', ' ')}, {c.get('source_time') or 'no recorded time'})")
    b.extra["draft_markdown"] = "\n".join(lines)
    b.extra["draft_title"] = title or f"Draft report: {inv.title}"
    for cf in summ["conflicts"]:
        b.conflicts.append(dict(cf, left_citation_ids=[remap[(id(summ), i)] for i in cf["left_citation_ids"] if (id(summ), i) in remap],
                                right_citation_ids=[remap[(id(summ), i)] for i in cf["right_citation_ids"] if (id(summ), i) in remap]))
    b.missing = summ["missing_information"] + chron["missing_information"]
    b.claim("Draft assembled from the investigation summary and chronology; see draft_markdown. Edit before saving or exporting.", "system_note")
    b.uncertainty.append("The draft is editable text. Saving or exporting it is the user's action; nothing has been published.")
    b.retrieval = {"method": "assembled_from_records", "records_considered": len(b.citations)}
    return b.to_dict(db, user)


# ----------------------------------------------------------------- related

def find_related(db: Session, user: AuthenticatedUser, record_type: str, record_id: str, *, limit: int = 8) -> dict:
    if record_type not in src.MODELS:
        raise invalid(f"record_type must be one of {tuple(src.MODELS)}")
    live = src.load_live(db, user.organization_id, record_type, record_id)
    if live is None or not src.can_view(db, user, record_type, live):
        raise not_found("Record")
    spec = src.build_doc(db, record_type, live)
    b = Builder("related")
    b.cite(cites.make_citation(db, user, record_type, record_id))
    seed = " ".join(query_terms(spec.title or "", 6))
    if seed:
        res = search_svc.search(db, user, seed, page=1, page_size=min(limit + 1, settings.RETRIEVAL_MAX_RESULTS))
        for h in res.items:
            if (h["record_type"], h["record_id"]) == (record_type, record_id):
                continue
            cid = b.cite(_hit_citation(h))
            b.claim(f"Shares keyword(s) {', '.join(h['matched_terms'])} with the selected record: {h['title']}", "record_summary", [cid])
    rels = _pair_all(db, user, record_type, record_id)
    for text, cit in rels:
        b.claim(text, "record_summary", [b.cite(cit)])
    if len(b.claims) == 0:
        b.status = "no_relevant_records"
        b.claim("No related records were found among the records you can access.", "system_note")
    b.uncertainty.append("Keyword overlap and recorded relationships are leads for review, not confirmation that records concern the same thing.")
    b.retrieval = {"method": "title_keywords+recorded_relationships", "query_terms": seed.split(), "semantic_used": False}
    return b.to_dict(db, user)


def _pair_all(db: Session, user: AuthenticatedUser, rt: str, rid: str) -> list[tuple[str, dict]]:
    out = []
    if rt in ("event", "evidence"):
        col_s = EvidenceRelationship.source_event_id if rt == "event" else EvidenceRelationship.source_evidence_id
        col_t = EvidenceRelationship.target_event_id if rt == "event" else EvidenceRelationship.target_evidence_id
        rows = db.execute(select(EvidenceRelationship).where(EvidenceRelationship.organization_id == user.organization_id,
                          EvidenceRelationship.is_reversed.is_(False), or_(col_s == rid, col_t == rid)).limit(30)).scalars().all()
        for r in rows:
            if r.source_event_id == rid or r.source_evidence_id == rid:
                other = ("event", r.target_event_id) if r.target_event_id else ("evidence", r.target_evidence_id)
            else:
                other = ("event", r.source_event_id) if r.source_event_id else ("evidence", r.source_evidence_id)
            c = cites.make_citation(db, user, other[0], other[1]) if other[1] else None
            if c:
                out.append((f"Recorded '{r.relationship_type}' relationship ({r.origin}, review status {r.review_status}) with {c['title']}.", c))
    rows = db.execute(select(InvestigationLink).where(InvestigationLink.organization_id == user.organization_id,
                      InvestigationLink.record_type == rt, InvestigationLink.record_id == rid).limit(20)).scalars().all()
    for l in rows:
        c = cites.make_citation(db, user, "investigation", l.investigation_id)
        if c:
            out.append((f"Linked to investigation \"{c['title']}\".", c))
    return out
