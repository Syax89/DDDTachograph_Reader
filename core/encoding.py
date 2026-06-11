"""Shared JSON encoder that handles bytes objects."""

import json


class BytesEncoder(json.JSONEncoder):
    """JSONEncoder that serializes bytes as hex strings and sets as sorted
    lists (parser results carry sets, e.g. ``calibration_vins``)."""

    def default(self, obj):
        if isinstance(obj, bytes):
            return obj.hex()
        if isinstance(obj, (set, frozenset)):
            return sorted(obj, key=str)
        return super().default(obj)
