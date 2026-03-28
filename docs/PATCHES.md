
## Patch #4: S3Vectors `update(vector=None)` crashes with boto3 validation error

**Symptom:**
```
ERROR mem0.memory.main: Error processing memory action: {'event': 'NONE'},
Error: Parameter validation failed:
Invalid type for parameter vectors[0].data.float32, value: None, type: <class 'NoneType'>
```

**Root cause:**
When `event=NONE` (memory content unchanged, only metadata needs updating), `mem0/memory/main.py`
calls `vector_store.update(vector_id, vector=None, payload=updated_metadata)`.

The S3Vectors `update()` implementation blindly calls `self.insert(vectors=[vector], ...)`,
passing `None` directly into `{"data": {"float32": None}}` — which fails boto3 parameter validation.

The OpenSearch adapter handles this correctly (`if vector is not None: doc["vector_field"] = vector`),
but S3Vectors does not.

**Fix (applied to site-packages):**
In `update()`, when `vector=None`, fetch the existing vector data via `get_vectors(returnData=True)`
before calling `insert`. If the existing data cannot be retrieved, skip the update with a warning.

**File:** `mem0/vector_stores/s3_vectors.py` — `update()` method  
**Upstream PR:** (to be submitted)  
**Applied:** 2026-03-28
