"""Local process admission and stable draft identity. One API process is supported."""
import asyncio
import inspect
from functools import wraps
from weakref import WeakKeyDictionary
from uuid import uuid5, NAMESPACE_URL

_locks=WeakKeyDictionary()


def serialize_local(function):
    @wraps(function)
    async def wrapped(*args,**kwargs):
        loop=asyncio.get_running_loop()
        lock=_locks.setdefault(loop,asyncio.Lock())
        async with lock:
            return await function(*args,**kwargs)
    wrapped.__signature__=inspect.signature(function,eval_str=True)
    return wrapped


def report_identity(plan_message_id):
    return str(uuid5(NAMESPACE_URL,'insight-report-plan:'+plan_message_id))


async def checkpoint(stage):
    """No-op seam for subprocess crash tests; no environment-controlled production kill."""
    return None
