"""Gemini band bo'lsa (503) yoki limitga yetilsa (429), biroz kutib qayta urinish."""

import asyncio
import logging

from google.genai import errors

RETRY_CODES = (429, 500, 503)
DELAYS = (2, 5, 10)


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


async def gemini_generate(client, **kwargs):
    return await with_retry(lambda: client.aio.models.generate_content(**kwargs))
