from django.urls import path  # noqa: F401

# Views land in later build-order steps (core loop, invites, etc.). The include is
# wired now so the URL namespace exists; patterns are added as views are built.
urlpatterns = []
