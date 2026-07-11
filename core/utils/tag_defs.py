"""Compatibility access to display names owned by :mod:`core.registry`.

The registry imports decoders while it is being built, so resolving it lazily
keeps this legacy utility import safe during package initialization.
"""

from collections.abc import Mapping


class _RegistryTagNames(Mapping):
    """Read-only mapping facade for callers that still import ``TACHO_TAGS``."""

    @staticmethod
    def _names():
        from core.registry.registry import DecoderRegistry
        return DecoderRegistry.instance().get_tag_names()

    def __getitem__(self, tag):
        return self._names()[tag]

    def __iter__(self):
        return iter(self._names())

    def __len__(self):
        return len(self._names())

    def copy(self):
        return self._names()


TACHO_TAGS = _RegistryTagNames()
