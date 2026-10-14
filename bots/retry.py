"""Gemini band bo'lsa (503) yoki limitga yetilsa (429), qayta urinish va zaxira modelga o'tish."""

import asyncio
import logging
import os

from google.genai import errors

RETRY_CODES = (429, 500, 503)
DELAYS = (2, 5, 10)

DEFAULT_MODEL = "gemini-3.5-flash-lite"
# Asosiy model band bo'lsa, navbat bilan shular sinab ko'riladi
FALLBACK_MODELS = [
    m.strip()
    for m in os.environ.get(
        "GEMINI_FALLBACK_MODELS",
        "gemini-3.5-flash-lite,gemini-flash-lite-latest,gemini-3.1-flash-lite",
    ).split(",")
    if m.strip()
]
# 404: model eskirgan yoki o'chirilgan bo'lsa ham keyingisiga o'tamiz
FALLBACK_CODES = RETRY_CODES + (404,)


async def with_retry(make_call):
    """make_call har safar yangi so'rov yaratadigan funksiya, masalan lambda."""
    for delay in DELAYS + (None,):
        try:
            return await make_call()
        except errors.APIError as e:
            if e.code not in RETRY_CODES or delay is None:
                raise
            logging.warning(f"Gemini {e.code}, {delay}s dan keyin qayta urinaman")
            await asyncio.sleep(delay)


def model_chain(model=None):
    chain = [model or DEFAULT_MODEL]
    chain += [m for m in FALLBACK_MODELS if m not in chain]
    return chain


async def gemini_generate(client, model=None, **kwargs):
    """generate_content: band model o'rniga zaxira modellarni ham sinaydi."""
    last_error = None
    for delay in (0, 5, 15):
        if delay:
            await asyncio.sleep(delay)
        for name in model_chain(model):
            try:
                return await client.aio.models.generate_content(model=name, **kwargs)
            except errors.APIError as e:
                if e.code not in FALLBACK_CODES:
                    raise
                last_error = e
                logging.warning(f"Gemini {name}: {e.code}, keyingi modelni sinayman")
    raise last_error
