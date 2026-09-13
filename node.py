import time
import string
import random
import threading
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

app = FastAPI()

# In-memory storage: short_code -> original_url 
store: dict[str, str] = {}
store_lock = threading.Lock()

# Operation log: append-only record of every shorten op 
operation_log: list[dict] = []


class ShortenRequest(BaseModel):
    url: str


def generate_code(length: int = 6) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(length))


@app.post("/shorten")
def shorten(body: ShortenRequest):
    with store_lock:
        code = generate_code()
        while code in store:  
            code = generate_code()

        store[code] = body.url
        operation_log.append({
            "op": "SHORTEN",
            "code": code,
            "url": body.url,
            "timestamp": time.time(),
        })

    return {"short_code": code, "original_url": body.url}

@app.get("/log")
def get_log():
    with store_lock:
        return {"log": operation_log, "entry_count": len(operation_log)}


@app.get("/health")
def health():
    return {"status": "alive"}


@app.get("/{code}")
def redirect(code: str):
    with store_lock:
        if code not in store:
            raise HTTPException(status_code=404, detail=f"Short code '{code}' not found")
        url = store[code]

    return RedirectResponse(url=url)


if __name__ == "__main__":
    import uvicorn
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    uvicorn.run(app, host="0.0.0.0", port=port)