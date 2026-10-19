class ProviderError(Exception):
    """A model/embedding provider failed. Messages are for server-side logs only."""


class ProviderTimeoutError(ProviderError):
    pass


class ProviderResponseError(ProviderError):
    """The provider answered, but the response was missing or malformed."""
