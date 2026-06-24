"""View-permission extension point for clips.

A clip's *base* visibility rules (PUBLIC is world-viewable; the uploader always
sees their own) live on the model, in ``Clip.is_viewable_by``. Feature apps that
can *additionally* grant view access — e.g. ``shared_collections`` lets an active
member view an UNLISTED clip in their collection — register a provider here at
app-ready time instead of ``clips`` importing those features.

This keeps the dependency one-directional: features depend on ``clips``, never
the reverse. A future consumer (watchparty) just registers its own provider.
"""

# Registered ``provider(clip, user) -> bool`` callables (any-of semantics).
_view_providers = []


def register_view_provider(provider):
    """Register an extra view-grant rule.

    ``provider(clip, user)`` is consulted only for the non-trivial case — an
    authenticated, non-uploader user viewing a non-PUBLIC clip — so providers may
    assume ``user`` is authenticated. Return True to *grant* view access.
    """
    _view_providers.append(provider)


def grants_view(clip, user):
    """Whether any registered provider grants ``user`` view access to ``clip``."""
    return any(provider(clip, user) for provider in _view_providers)
