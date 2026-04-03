# patch_s3vectors_filter.py
import re, sys

try:
    import mem0.vector_stores.s3_vectors as m
    filepath = m.__file__
except ImportError:
    print("Error: mem0 not installed")
    sys.exit(1)

with open(filepath, 'r') as f:
    content = f.read()

# ── Patch 1: inject/replace _convert_filters method ──
new_method = '''    def _convert_filters(self, filters: dict) -> dict:
        """Convert mem0 filter dict to S3Vectors metadata filter format.
        
        S3Vectors uses MongoDB-style operators: {"field": {"$eq": "value"}}
        Multiple conditions are combined with $and.
        """
        if not filters:
            return None
        conditions = []
        for key, value in filters.items():
            conditions.append({key: {"$eq": value}})
        if len(conditions) == 1:
            return conditions[0]
        elif len(conditions) > 1:
            return {"$and": conditions}
        return None'''

new_content = re.sub(
    r'    def _convert_filters\(self.*?(?=\n    def )',
    new_method + '\n',
    content,
    flags=re.DOTALL
)

if new_content == content:
    # Method doesn't exist yet, inject before search()
    new_content = content.replace(
        '    def search(self,',
        new_method + '\n\n    def search(self,'
    )

# ── Patch 2: make search() call _convert_filters before passing filter to API ──
# Replace the line: params["filter"] = filters
# With: params["filter"] = self._convert_filters(filters)
new_content = new_content.replace(
    '            params["filter"] = filters',
    '            params["filter"] = self._convert_filters(filters)'
)

with open(filepath, 'w') as f:
    f.write(new_content)
print(f"Patched: {filepath}")

