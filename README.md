# Fault-Tolerant URL Shortener

A URL shortener built to explore distributed systems concepts: leader-based
replication, heartbeat-based failure detection, and automatic failover.
Under the hood, it's a small distributed key-value store (the URL
shortener is a relatable wrapper around that core mechanic).

## What it does

- Shortens a URL and stores the mapping across 3 replicated nodes.
- One node is the "leader" (accepts writes); the other two are "followers"
  (replicate writes, serve reads).
- If the leader crashes, followers detect it via missed heartbeats and
  automatically elect a new leader. The system keeps accepting writes with no manual intervention, and writes that had replicated to at least one follower before the crash are preserved.
- Writes are protected by a shared API key.
- A browser dashboard shows live node status and lets users trigger a
  simulated leader crash to watch failover happen in real time.

## Architecture
```
                 ┌─────────────┐
                 │   Client    │
                 │ (dashboard  │
                 │  or curl)   │
                 └──────┬──────┘
                        │ writes only go to the leader
                        ▼
                 ┌─────────────┐
                 │   Node 0    │
                 │  (LEADER)   │
                 └──────┬──────┘
          replicates on every write
          ┌─────────────┴─────────────┐
          ▼                           ▼
   ┌─────────────┐             ┌─────────────┐
   │   Node 1    │◄──────────► │   Node 2    │
   │ (FOLLOWER)  │  heartbeat  │ (FOLLOWER)  │
   └─────────────┘   pings to  └─────────────┘
          │           leader          │
          └───────────┬───────────────┘
                      ▼
          If leader misses 3 consecutive
          heartbeats (~1.5s), followers
          elect the lowest surviving
          node ID as the new leader.

```

**Write path:** Client → Leader → Leader applies write locally → Leader
forwards write to both followers → followers apply it too.

**Read path:** Client can read (resolve a short code) from *any* node —
leader or follower — since all nodes hold a replicated copy.

**Failure path:** Followers ping the leader's `/health` every 500ms. On
3 consecutive missed pings, a follower declares the leader dead, checks
which other nodes are still alive, and the lowest surviving node ID
becomes the new leader.

## Running it locally

Requires Python 3.10+.

```bash
pip3 install -r requirements.txt
```

Start all 3 nodes (each in its own terminal):

```bash
python3 node.py 8000 --role=leader --node-id=0 \
  --nodes="0:http://localhost:8000,1:http://localhost:8001,2:http://localhost:8002"

python3 node.py 8001 --role=follower --node-id=1 \
  --nodes="0:http://localhost:8000,1:http://localhost:8001,2:http://localhost:8002"

python3 node.py 8002 --role=follower --node-id=2 \
  --nodes="0:http://localhost:8000,1:http://localhost:8001,2:http://localhost:8002"
```

Open `dashboard.html` directly in your browser.

## Demo walkthrough

1. Paste a URL into the dashboard, click **Shorten**, a short link appears.
2. Click the resulting link, confirms it resolves correctly.
3. Click **"Kill Current Leader"**, watch the leader's box turn red
   (dead), and within ~2 seconds a follower's box turns green (elected
   as the new leader). The event log shows the role change.
4. Shorten another URL, it routes to the new leader and succeeds,
   proving the system recovered without any manual restart.

### Manual API testing

```bash
# Shorten (requires API key)
curl -X POST http://localhost:8000/shorten \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-secret-key" \
  -d '{"url": "https://www.google.com"}'

# Redirect (works from any node)
curl -i http://localhost:8001/<short_code>

# Health / role check
curl http://localhost:8000/health
```

## Design decisions & trade-offs

- **Simplified leader election, not full Raft.** New leader is chosen
  as "lowest surviving node ID" - no term numbers, no quorum voting,
  no log-completeness checks. This is sufficient to demonstrate
  automatic failover but doesn't handle every edge case a production
  consensus algorithm (Raft/Paxos) would.
- **In-memory storage only.** No persistence to disk, no log
  compaction or snapshotting. A node losing power loses its data;
  acceptable for this project's scope.
- **Crash-failure only, not network partitions.** The system assumes a
  node is either fully alive or fully dead - it doesn't handle the
  harder case of a node being alive but network-isolated from others
  (which can cause more subtle "split-brain" bugs in real systems).
- **Follower catch-up is not implemented.** If a follower is
  unreachable when the leader replicates a write, that write is
  logged as a warning and skipped for that follower — there's no
  mechanism for the follower to catch up on missed writes when it
  comes back online. A full solution would require the leader to
  track each follower's last-acknowledged operation and replay its
  log from that point — a meaningful scope increase intentionally
  left out here.
- **Shared API key, not per-user auth.** A single hardcoded key
  gates all writes. This demonstrates the principle of restricting
  write access, but isn't a production-grade auth system (no user
  identity, no key rotation/expiry). Per-user JWT-based auth is
  something I implemented separately in another project (Flowboard).

## Tech stack

Python, FastAPI, Uvicorn, `requests` (for inter-node communication),
vanilla HTML/JS (dashboard).