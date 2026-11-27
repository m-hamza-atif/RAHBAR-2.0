"""Readiness, semantic cache, retrieval floor, validation and safe fallback."""
from __future__ import annotations
import json
import logging
from fastapi import HTTPException
from pydantic import ValidationError
from ..config import Settings
from ..embeddings import embed_query
from ..logjson import request_id_var
from ..providers.llm.base import Generation, LLMProvider, count_tokens
from ..providers.llm.stub import abstention
from ..retrieval.base import Retriever
from ..routes import metrics
from ..schemas import Answer, AskResponse, RetrievedRef, Passage
from .cache import SemanticCache, follow_up
from .readiness import check
from .grounding import preserve_obligations, protect_evidence
from .prompt import POISON
from .trace import CURRENT_TRACE, QueryTrace

log = logging.getLogger('rahbar.answer')


def validate_answer(raw: Answer | str, passages: list[Passage]) -> Answer:
    answer = Answer.model_validate_json(raw.model_dump_json() if isinstance(raw, Answer) else raw)
    valid = {(p.source, p.section, p.page) for p in passages}
    if any((c.source, c.section, c.page) not in valid for c in answer.citations):
        raise ValueError('citation not present in retrieved evidence')
    if answer.answered_from_context and (not answer.citations or not answer.answer.strip()):
        raise ValueError('grounded answers require text and citations')
    if not answer.answered_from_context and (answer.citations or answer.confidence != 'low'):
        raise ValueError('abstentions require empty citations and low confidence')
    # Do not display unsupported claims merely because the model labelled them ungrounded.
    return answer if answer.answered_from_context else abstention()


def answer_question(question: str, retriever: Retriever, provider: LLMProvider,
                    settings: Settings, cache: SemanticCache,
                    history: list | None = None, bypass_cache: bool = False) -> AskResponse:
    history = history or []
    passages: list[Passage] = []
    cached = False
    abstained = True
    trace = QueryTrace(question, settings, provider.name)
    trace.filters["retriever"] = retriever.name
    trace_token = CURRENT_TRACE.set(trace)
    status = 503
    response: AskResponse | None = None
    try:
        checks, revision = check(retriever, cache)
        if not revision:
            raise HTTPException(503, detail={'checks': checks})
        trace.record["index_revision"] = revision
        followup = bypass_cache or follow_up(question, history)
        # History is untrusted context, never system instructions; it is never cached.
        search_question = question
        if history:
            previous = [m['content'] for m in history if m.get('role') == 'user']
            search_question = (' '.join(previous[-2:])+' '+question).strip()
        trace.record["rewritten_query"] = search_question
        if POISON.search(search_question):
            trace.actions.append({"action": "query_instruction_flagged", "source": "query"})
            followup = True
        with trace.stage("embed"):
            vector = embed_query(search_question, settings)
        if not followup:
            with trace.stage("cache"):
                hit = cache.find(question, vector, revision)
            if hit and retriever.snapshot() == revision:
                cached = True
                abstained = False
                metrics.CACHE_HITS.inc()
                metrics.update_cache_ratio()
                passages = [Passage(**r.model_dump(), text='') for r in hit.retrieved]
                trace.record.update(cache_source_trace_id=hit.trace_id, generation_status="cache_hit",
                                    generation_skip_reason="cached_response")
                response = hit.model_copy(update={'request_id': request_id_var.get(), 'cached': True,
                                                  'trace_id': trace.trace_id})
                status = 200
                return response
        metrics.CACHE_MISSES.inc()
        metrics.update_cache_ratio()
        with metrics.RETRIEVAL.time(), trace.stage("retrieve"):
            retrieved = retriever.retrieve(question, settings.top_k, vector)
        trace.record["retrieved_chunks"] = [
            p.model_dump(exclude={"text"}) for p in retrieved]
        trace.record["top1_similarity"] = max((p.score for p in retrieved), default=None)
        with trace.stage("rerank"):
            passages, actions = protect_evidence(
                [p for p in retrieved if p.score >= settings.relevance_floor])
        trace.actions.extend(actions)
        trace.record["reranked_order"] = [p.chunk_id for p in passages]
        trace.record["context_passages"] = [p.model_dump() for p in passages]
        if not passages:
            trace.record["generation_skip_reason"] = (
                "guardrail_removed_all_context" if actions else
                "below_relevance_floor" if retrieved else "no_retrieved_passages")
        if retriever.snapshot() != revision:
            raise HTTPException(503, detail='Index changed during retrieval; retry the question.')
        answer = abstention()
        validated = False
        if passages:
            error = ''
            prompt_question = question
            if history:
                prompt_question += '\nUntrusted conversation context: '+json.dumps(history)
            trace.record.update(generation_question=prompt_question, generation_status="failed")
            for attempt in range(2):
                try:
                    with metrics.GENERATION.time(), trace.stage("generate"):
                        generated = provider.generate(prompt_question, passages, error)
                    if isinstance(generated, Generation):
                        metrics.PROMPT_TOKENS.inc(max(0, generated.prompt_tokens))
                        metrics.COMPLETION_TOKENS.inc(max(0, generated.completion_tokens))
                        raw: Answer | str = generated.text
                    else:
                        raw = generated
                        metrics.PROMPT_TOKENS.inc(count_tokens(prompt_question+' '.join(p.text for p in passages)))
                        metrics.COMPLETION_TOKENS.inc(count_tokens(
                            raw.model_dump_json() if isinstance(raw, Answer) else raw))
                    answer = validate_answer(raw, passages)
                    answer = validate_answer(preserve_obligations(answer, passages), passages)
                    trace.record["generation_status"] = "completed"
                    validated = attempt == 0  # responses requiring correction are never cached
                    break
                except Exception as exc:
                    feedback = type(exc).__name__
                    if isinstance(exc, ValidationError):
                        feedback = json.dumps(exc.errors(
                            include_input=False, include_url=False, include_context=False))[:1500]
                    elif isinstance(exc, ValueError) and str(exc) in {
                            'citation not present in retrieved evidence',
                            'grounded answers require text and citations',
                            'abstentions require empty citations and low confidence'}:
                        feedback = str(exc)
                    error = ('Output must match the Answer JSON schema and cite only supplied evidence. '
                             + feedback)
                    trace.actions.append({"action": "generation_validation_failed",
                                          "error_type": type(exc).__name__, "attempt": attempt + 1})
                    log.warning('generation_validation_failed', extra={'attempt': attempt+1,
                                                                     'error_type': type(exc).__name__})
                    if attempt == 1:
                        metrics.FALLBACKS.inc()
                        answer = abstention().model_copy(update={
                            'reasoning': 'Generation or citation verification failed after one retry.',
                            'answer': 'I could not produce a verified answer from the retrieved policy evidence. '
                                      'Please consult the source documents.'})
        # Reject even successful output if a rebuild raced generation.
        if retriever.snapshot() != revision:
            raise HTTPException(503, detail='Index changed during generation; retry the question.')
        abstained = not answer.answered_from_context
        if abstained:
            metrics.ABSTENTIONS.inc()
        response = AskResponse(request_id=request_id_var.get(), answer=answer.answer,
            citations=answer.citations, answered_from_context=answer.answered_from_context,
            confidence=answer.confidence, retrieved=[RetrievedRef(**p.model_dump()) for p in passages],
            provider=provider.name, cached=False, trace_id=trace.trace_id)
        # Only an already-sanitized, first-attempt grounded response is eligible.
        never_cache = followup or not validated or not answer.answered_from_context
        if not never_cache:
            with trace.stage("cache"):
                cache.put(question, vector, revision, response)
        status = 200
        return response
    except HTTPException as exc:
        status = exc.status_code
        trace.record["error"] = exc.detail
        raise
    except Exception as exc:
        log.error('query_dependency_failed', extra={'error_type': type(exc).__name__})
        trace.record["error"] = type(exc).__name__
        raise HTTPException(503, detail='Query dependency unavailable; check /readyz.') from None
    finally:
        CURRENT_TRACE.reset(trace_token)
        trace.finish()
        trace.record.update(status=status, cache_hit=cached)
        if response is not None and status == 200:
            trace.record.update(response=response.answer,
                                citations=[citation.model_dump() for citation in response.citations],
                                abstained=abstained)
        metrics.observe_query_trace(trace.record)
        if not trace.emit(settings.trace_dir):
            metrics.TRACE_WRITE_FAILURES.inc()
        log.info('query_summary', extra={'top_k': settings.top_k,
            'trace_id': trace.trace_id,
            'retrieved_chunk_ids': [p.chunk_id for p in passages],
            'similarity_scores': [round(p.score, 4) for p in passages],
            'cache_hit': cached, 'abstained': abstained})
