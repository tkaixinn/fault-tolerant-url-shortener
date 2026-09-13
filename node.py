import time
import string
import random
import threading
import sys
import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

app = FastAPI()

ROLE = "leader"        
NODE_ID = 0              
PEERS: list[str] = []   

store: dict[str, str] = {}
store_lock = threading.Lock()

operation_log: list[dict] = []


class ShortenRequest(BaseModel):
    url: str


class ReplicateRequest(BaseModel):
    code: str
    url: str
    timestamp: float


def generate_code(length: int = 6) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(length))


def apply_write(code: str, url: str, timestamp: float):
    """Apply a write to local storage + log. Used by both the leader
    (on a new client write) and followers (on a replicated write)."""
    with store_lock:
        store[code] = url
        operation_log.append({
            "op": "SHORTEN",
            "code": code,
            "url": url,
            "timestamp": timestamp,
        })


@app.post("/shorten")
def shorten(body: ShortenRequest):
    if ROLE != "leader":
        raise HTTPException(
            status_code=403,
            detail="This node is a follower — writes must go through the leader",
        )

    code = generate_code()
    with store_lock:
        while code in store:
            code = generate_code()
    timestamp = time.time()

    apply_write(code, body.url, timestamp)

    for peer in PEERS:
        try:
            requests.post(
                f"{peer}/replicate",
                json={"code": code, "url": body.url, "timestamp": timestamp},
                timeout=1,
            )
        except requests.exceptions.RequestException:
            print(f"[WARN] Failed to replicate to {peer}")

    return {"short_code": code, "original_url": body.url}


@app.post("/replicate")
def replicate(body: ReplicateRequest):
    """Followers receive writes here from the leader."""
    if ROLE == "leader":
        raise HTTPException(status_code=403, detail="Leader does not accept /replicate calls")

    apply_write(body.code, body.url, body.timestamp)
    return {"status": "replicated", "code": body.code}


@app.get("/log")
def get_log():
    with store_lock:
        return {"log": operation_log, "entry_count": len(operation_log)}


@app.get("/health")
def health():
    return {"status": "alive", "role": ROLE, "node_id": NODE_ID}


@app.get("/{code}")
def redirect(code: str):
    with store_lock:
        if code not in store:
            raise HTTPException(status_code=404, detail=f"Short code '{code}' not found")
        url = store[code]
    return RedirectResponse(url=url)


if __name__ == "__main__":
    import uvicorn
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("port", type=int)
    parser.add_argument("--role", choices=["leader", "follower"], default="leader")
    parser.add_argument("--node-id", type=int, default=0)
    parser.add_argument("--peers", type=str, default="", help="comma-separated peer URLs")
    args = parser.parse_args()

    ROLE = args.role
    NODE_ID = args.node_id
    PEERS = [p for p in args.peers.split(",") if p]

    print(f"Starting node {NODE_ID} as {ROLE.upper()} on port {args.port}, peers={PEERS}")
    uvicorn.run(app, host="0.0.0.0", port=args.port)