import json
import uuid
import azure.functions as func

def create_response(status_code: int, ok: bool, data=None, error: str = None, trace_id: str = None) -> func.HttpResponse:
    trace = trace_id or str(uuid.uuid4())
    payload = {
        "ok": ok,
        "data": data,
        "error": error,
        "trace_id": trace
    }
    return func.HttpResponse(
        body=json.dumps(payload),
        status_code=status_code,
        mimetype="application/json"
    )