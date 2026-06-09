"""Shared JSON encoder that handles bytes objects."""

import json


class BytesEncoder(json.JSONEncoder):
    """JSONEncoder that serializes bytes as hex strings."""

    def default(self, obj):
        if isinstance(obj, bytes):
            return obj.hex()
        return super().default(obj)
