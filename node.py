import time
import string
import random
import threading
import os
import requests
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY = os.environ.get("KV_API_KEY", "dev-secret-key")

ROLE = "leader"          
NODE_ID = 0
ALL_NODES: dict[int, str] = {}  
LEADER_ID = 0            

HEARTBEAT_INTERVAL = 0.5  
MISSED_HEARTBEAT_LIMIT = 3

missed_heartbeats = 0
election_lock = threading.Lock()

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
    with store_lock:
        store[code] = url
        operation_log.append({
            "op": "SHORTEN",
            "code": code,
            "url": url,
            "timestamp": timestamp,
        })


def peers_excluding_self() -> dict[int, str]:
    return {nid: addr for nid, addr in ALL_NODES.items() if nid != NODE_ID}


@app.post("/shorten")
def shorten(body: ShortenRequest, x_api_key: str = Header(None)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    if ROLE != "leader":
        raise HTTPException(
            status_code=403,
            detail=f"This node is a follower — writes must go through the leader (node {LEADER_ID})",
        )

    code = generate_code()
    with store_lock:
        while code in store:
            code = generate_code()
    timestamp = time.time()

    apply_write(code, body.url, timestamp)

    for nid, addr in peers_excluding_self().items():
        try:
            requests.post(
                f"{addr}/replicate",
                json={"code": code, "url": body.url, "timestamp": timestamp},
                timeout=1,
            )
        except requests.exceptions.RequestException:
            print(f"[WARN] Failed to replicate to node {nid} ({addr})")

    return {"short_code": code, "original_url": body.url}


@app.post("/replicate")
def replicate(body: ReplicateRequest):
    if ROLE == "leader":
        raise HTTPException(status_code=403, detail="Leader does not accept /replicate calls")
    apply_write(body.code, body.url, body.timestamp)
    return {"status": "replicated", "code": body.code}


@app.post("/kill")
def kill():
    """Simulates a hard crash for demo purposes — forcibly exits the
    process without graceful shutdown, mimicking a real crash rather
    than a clean stop."""
    print(f"[DEMO] Node {NODE_ID} received /kill — simulating a crash NOW")
    threading.Timer(0.1, lambda: os._exit(1)).start()
    return {"status": "dying"}


@app.get("/log")
def get_log():
    with store_lock:
        return {"log": operation_log, "entry_count": len(operation_log)}


@app.get("/health")
def health():
    return {"status": "alive", "role": ROLE, "node_id": NODE_ID, "leader_id": LEADER_ID}


@app.get("/{code}")
def redirect(code: str):
    with store_lock:
        if code not in store:
            raise HTTPException(status_code=404, detail=f"Short code '{code}' not found")
        url = store[code]
    return RedirectResponse(url=url)


def become_leader():
    global ROLE, LEADER_ID
    with election_lock:
        if ROLE != "leader":
            ROLE = "leader"
            LEADER_ID = NODE_ID
            print(f"[ELECTION] Node {NODE_ID} is now the LEADER")


def heartbeat_loop():
    """Runs only on followers. Pings the current leader; if it fails
    too many times in a row, triggers a simplified election."""
    global missed_heartbeats, LEADER_ID

    while True:
        time.sleep(HEARTBEAT_INTERVAL)

        if ROLE == "leader":
            continue  

        leader_addr = ALL_NODES.get(LEADER_ID)
        if leader_addr is None:
            continue

        try:
            resp = requests.get(f"{leader_addr}/health", timeout=0.4)
            if resp.status_code == 200:
                missed_heartbeats = 0
                continue
        except requests.exceptions.RequestException:
            pass

        # If we reach here, the heartbeat failed
        missed_heartbeats += 1
        print(f"[HEARTBEAT] Missed heartbeat #{missed_heartbeats} to leader {LEADER_ID}")

        if missed_heartbeats >= MISSED_HEARTBEAT_LIMIT:
            trigger_election()


def trigger_election():
    """Simplified leader election: the surviving node with the lowest
    node_id becomes the new leader. This is NOT full Raft — no term
    numbers, no quorum voting, no handling of network partitions
    beyond simple crash-failure. Documented as a scoping decision."""
    global LEADER_ID, missed_heartbeats

    print(f"[ELECTION] Node {NODE_ID} declares leader {LEADER_ID} dead. Starting election...")

    alive_nodes = [NODE_ID] 
    for nid, addr in peers_excluding_self().items():
        if nid == LEADER_ID:
            continue  
        try:
            resp = requests.get(f"{addr}/health", timeout=0.4)
            if resp.status_code == 200:
                alive_nodes.append(nid)
        except requests.exceptions.RequestException:
            pass

    new_leader_id = min(alive_nodes)
    print(f"[ELECTION] Surviving nodes: {alive_nodes}. New leader elected: node {new_leader_id}")

    LEADER_ID = new_leader_id
    missed_heartbeats = 0

    if new_leader_id == NODE_ID:
        become_leader()


if __name__ == "__main__":
    import uvicorn
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("port", type=int)
    parser.add_argument("--role", choices=["leader", "follower"], default="leader")
    parser.add_argument("--node-id", type=int, default=0)
    parser.add_argument("--nodes", type=str, required=True,
                         help="comma-separated node_id:address pairs, e.g. 0:http://localhost:8000,1:http://localhost:8001")
    args = parser.parse_args()

    ROLE = args.role
    NODE_ID = args.node_id

    for pair in args.nodes.split(","):
        nid_str, addr = pair.split(":", 1)
        ALL_NODES[int(nid_str)] = addr

    LEADER_ID = 0  

    print(f"Starting node {NODE_ID} as {ROLE.upper()} on port {args.port}")
    print(f"Known nodes: {ALL_NODES}")

    if ROLE == "follower":
        t = threading.Thread(target=heartbeat_loop, daemon=True)
        t.start()

    uvicorn.run(app, host="0.0.0.0", port=args.port)