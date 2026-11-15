"""Asynchronous AI Microservice Proxy with strict <8.5s latency budget and TTL cache."""

import logging
import time
from typing import Dict, Optional, Tuple
import httpx
from app.config import settings
from app.schemas import AskRequest, AskResponse
from app.seed_data import GROUNDED_QA_FALLBACK

logger = logging.getLogger("flamesight.ai_proxy")


class AIProxyService:
    """Manages pooled HTTP client connections to flamesight RAG, in-memory TTL caching,

    strict latency budgeting (<8.5s), and grounded fallback answers.
    """

    def __init__(self) -> None:
        self.client: Optional[httpx.AsyncClient] = None
        # Cache key: normalized question text -> (AskResponse, expire_at)
        self._cache: Dict[str, Tuple[AskResponse, float]] = {}

    def init_client(self) -> None:
        """Initialize pooled HTTP client during app lifespan startup."""
        limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
        self.client = httpx.AsyncClient(
            limits=limits,
            timeout=settings.AI_PROXY_TIMEOUT_SECONDS,
            headers={"User-Agent": "FlameSight-BFF/v0.1"},
        )
        logger.info("Initialized pooled AsyncClient with timeout %ss.", settings.AI_PROXY_TIMEOUT_SECONDS)

    async def close_client(self) -> None:
        """Close HTTP client during app shutdown."""
        if self.client is not None:
            await self.client.aclose()
            self.client = None
            logger.info("Closed AI proxy AsyncClient.")

    def clear_cache(self) -> int:
        """Clear all entries from the in-memory TTL cache."""
        count = len(self._cache)
        self._cache.clear()
        logger.info("Cleared %d entries from in-memory cache.", count)
        return count

    def _get_from_cache(self, question: str) -> Optional[AskResponse]:
        """Retrieve unexpired cached response if available."""
        key = question.strip().lower()
        if key in self._cache:
            resp, expire_at = self._cache[key]
            if time.time() < expire_at:
                return resp
            else:
                del self._cache[key]
        return None

    def _store_in_cache(self, question: str, response: AskResponse) -> None:
        """Save response in TTL cache."""
        key = question.strip().lower()
        expire_at = time.time() + settings.CACHE_TTL_SECONDS
        self._cache[key] = (response, expire_at)

    def grounded_stub_fallback(self, question: str, start_time: float) -> AskResponse:
        """Scientifically grounded fallback matching the Frontend contract.

        Rules (exact match with Frontend/src/lib/api.ts STUB_ASK_ROUTES):
        - keywords ["moon", "30%"] -> Moon Base 30% O2 answer (grounded=True, citations 2-4)
        - keywords ["saffire", "bass"] -> BASS / Saffire answer (grounded=True, citations 2-4)
        - keywords ["smoke"] -> Smoke aerosol / SAME answer (grounded=True, citations 2-4)
        - anything else -> not in the data (grounded=False, answer="", citations=[], evidence=None)
        """
        q = question.lower()
        latency_ms = round((time.time() - start_time) * 1000, 1)

        # 1. Moon Base / 30% O2 query (keywords: "moon", "30%")
        if any(term in q for term in ["moon", "30%"]):
            base = GROUNDED_QA_FALLBACK["moon"]
            return base.model_copy(update={"latency_ms": latency_ms})

        # 2. Saffire or BASS query (keywords: "saffire", "bass")
        if any(term in q for term in ["saffire", "bass"]):
            base = GROUNDED_QA_FALLBACK["saffire_bass"]
            return base.model_copy(update={"latency_ms": latency_ms})

        # 3. Smoke detection / aerosol query (keywords: "smoke")
        if any(term in q for term in ["smoke"]):
            base = GROUNDED_QA_FALLBACK["smoke"]
            return base.model_copy(update={"latency_ms": latency_ms})

        # 4. Out of scope / unanswerable -> "Not in the data"
        # Hard Rule: answer MUST be empty string, citations must be empty, evidence must be None
        base = GROUNDED_QA_FALLBACK["not_in_data"]
        return base.model_copy(update={"latency_ms": latency_ms})

    async def ask(self, req: AskRequest) -> AskResponse:
        """Route natural language question to upstream flamesight RAG service,

        falling back cleanly within <8.5s budget.
        """
        t0 = time.time()

        # Check in-memory TTL cache first (instant response for repeat queries)
        cached_resp = self._get_from_cache(req.question)
        if cached_resp is not None:
            return cached_resp

        # Check if upstream AI service is configured
        ai_url = (settings.AI_SERVICE_URL or "").strip()
        if not ai_url:
            fallback = self.grounded_stub_fallback(req.question, t0)
            self._store_in_cache(req.question, fallback)
            return fallback

        # Ensure client is ready
        if self.client is None:
            self.init_client()

        target_url = f"{ai_url.rstrip('/')}/ask"
        try:
            logger.info("Proxying /ask query to upstream AI service: %s", target_url)
            # Timeout is 8.0s, safe below browser 10s budget
            response = await self.client.post(
                target_url,
                json={"question": req.question},
            )

            if response.status_code == 200:
                data = response.json()
                latency_ms = round((time.time() - t0) * 1000, 1)
                data["latency_ms"] = latency_ms

                # Normalize citations from flamesight upstream (title -> paper_title, url -> source_url)
                if "citations" in data and isinstance(data["citations"], list):
                    normalized_cits = []
                    for cit in data["citations"][:4]:  # Cap at max 4 citations
                        if isinstance(cit, dict):
                            c = dict(cit)
                            if "paper_title" not in c and "title" in c:
                                c["paper_title"] = c.pop("title")
                            if "source_url" not in c and "url" in c:
                                c["source_url"] = c.pop("url")
                            normalized_cits.append(c)
                        else:
                            normalized_cits.append(cit)
                    data["citations"] = normalized_cits

                # Enforce contract: when grounded is False, answer MUST be "" and evidence MUST be None
                if not data.get("grounded", True):
                    data["grounded"] = False
                    data["answer"] = ""
                    data["citations"] = []
                    data["evidence"] = None

                ask_resp = AskResponse.model_validate(data)
                self._store_in_cache(req.question, ask_resp)
                return ask_resp
            else:
                logger.warning(
                    "Upstream AI service returned HTTP %s. Falling back to grounded stub.",
                    response.status_code,
                )
        except Exception as exc:
            logger.warning(
                "Upstream AI proxy timed out or failed (%s). Falling back to grounded stub.",
                str(exc),
            )

        # Not cached: a timeout while the AI service wakes up (Render free tier) must not pin the stub answer
        # for CACHE_TTL_SECONDS; the next request should reach the real service again.
        return self.grounded_stub_fallback(req.question, t0)


ai_proxy_service = AIProxyService()
