import asyncio, httpx

async def post_with_backoff(url: str, payload: dict, max_tries: int = 6):
    """POST JSON with exponential backoff until a 200 OK or attempts exhausted."""
    delay = 1
    async with httpx.AsyncClient(timeout=20) as client:
        for _ in range(max_tries):
            try:
                r = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
                if r.status_code == 200:
                    return True, r.text
            except Exception as e:
                last_err = str(e)
            await asyncio.sleep(delay)
            delay *= 2
    return False, last_err if 'last_err' in locals() else "Unknown error"
