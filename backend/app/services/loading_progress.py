"""Best-effort short-lived loading telemetry; never blocks recording work."""
import json
import time
from contextvars import ContextVar
try:
    from redis import Redis
except ImportError:
    Redis = None
from app.core.config import settings

current = ContextVar("survey_loading", default=None)
client = Redis.from_url(settings.redis_url, socket_connect_timeout=.2, socket_timeout=.2) if Redis else None

def report(percent, stage, status="running"):
    state = current.get()
    if not state: return
    now = time.monotonic()
    if status == "running" and now-state["last"] < .5: return
    state["last"] = now
    state["percent"] = max(state["percent"], percent)
    try:
        client.setex("survey-loading:"+state["id"], 3600, json.dumps({"percent":state["percent"],"stage":stage,"status":status}))
    except Exception: pass

def read(identifier):
    try:
        value = client.get("survey-loading:"+identifier)
        return json.loads(value) if value else {"status":"pending"}
    except Exception: return {"status":"unavailable"}

class operation:
    def __init__(self, identifier): self.identifier = str(identifier) if identifier else None
    def __enter__(self):
        self.token = current.set({"id":self.identifier,"last":0,"percent":0} if self.identifier else None)
        report(0,"Loading recording")
    def __exit__(self, kind, value, traceback):
        report(95 if kind is None else 0, "Preparing map" if kind is None else "Loading failed", "ready" if kind is None else "failed")
        current.reset(self.token)
