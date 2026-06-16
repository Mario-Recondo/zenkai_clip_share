from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView

from shared_collections.permissions import destroy_clip

from .forms import (
    ALLOWED_EXTENSIONS,
    MAX_DURATION_SECONDS,
    MAX_UPLOAD_SIZE,
    ClipCreateForm,
)
from .models import Clip
from .services import enqueue_transcode

PAGE_SIZE = 12


# Create your views here.
@login_required
def clip_list(request):
    # select_related avoids an N+1 on clip.uploader.username (Flaw #4)
    clip_qs = Clip.objects.select_related("uploader").order_by("-date_uploaded")
    query = request.GET.get("q", "").strip()
    if query:
        clip_qs = clip_qs.filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(uploader__username__icontains=query)
        )
    page_obj = Paginator(clip_qs, PAGE_SIZE).get_page(request.GET.get("page"))
    context = {
        "clips": page_obj,
        "page_obj": page_obj,
        "query": query,
        "title": f"Search: {query}" if query else "Recent Clips",
    }
    return render(request, "clips/clip_list.html", context)


def clip_detail(request, pk):
    clip = get_object_or_404(Clip.objects.select_related("uploader"), pk=pk)
    return render(
        request, "clips/clip_detail.html", {"clip": clip, "title": clip.title}
    )


def clip_status(request, pk):
    """Tiny JSON endpoint polled by the frontend while a clip transcodes."""
    clip = get_object_or_404(Clip.objects.only("status", "thumbnail"), pk=pk)
    return JsonResponse(
        {
            "status": clip.status,
            "thumbnail_url": clip.thumbnail.url if clip.thumbnail else None,
        }
    )


# class based view for uploading clips
class ClipCreateView(LoginRequiredMixin, CreateView):
    model = Clip
    form_class = ClipCreateForm
    template_name = "clips/clip_create.html"
    # Back to the grid, where the new clip appears first with a live
    # "Processing" badge (see static/js/clip-status.js).
    success_url = reverse_lazy("clip-list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Upload a Clip"
        # Upload limits for the dropzone's client-side pre-checks; forms.py
        # stays the single source of truth.
        context["max_upload_size"] = MAX_UPLOAD_SIZE
        context["max_duration_seconds"] = MAX_DURATION_SECONDS
        context["allowed_extensions"] = ",".join(sorted(ALLOWED_EXTENSIONS))
        return context

    @staticmethod
    def _is_ajax(request):
        return request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def form_valid(self, form):
        form.instance.uploader = self.request.user
        # Save the row (and file) inside a transaction and enqueue only after it
        # commits, so a rolled-back clip can never leave a queued transcode job.
        with transaction.atomic():
            response = super().form_valid(form)
        transaction.on_commit(lambda: enqueue_transcode(self.object))
        if self._is_ajax(self.request):
            return JsonResponse({"redirect": str(self.get_success_url())})
        return response

    def form_invalid(self, form):
        if self._is_ajax(self.request):
            return JsonResponse({"errors": form.errors}, status=400)
        return super().form_invalid(form)


class ClipDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    """Collection-aware My-clips delete.

    When the clip lives in 1+ collections the confirm page offers two choices:

    - **Unpublish** (default, non-destructive): set ``visibility = UNLISTED``.
      This is a *global* change — the clip leaves every public surface at once
      (home feed, the public uploader listing, anonymous detail/status links) but
      stays in its shared collections so members keep access.
    - **Delete everywhere** (destructive): route through ``destroy_clip`` so the
      single full-destroy entry point — and never a silent bypass — removes the
      row, cascades all collection links, and cleans up files.

    A clip in no collection has only the destructive path (today's behaviour).
    """

    model = Clip
    template_name = "clips/clip_confirm_delete.html"
    success_url = reverse_lazy("clip-list")

    def test_func(self):
        # Only the uploader may delete their clip (403 otherwise).
        return self.get_object().uploader == self.request.user

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["collections"] = list(self.object.collections.all())
        return context

    def form_valid(self, form):
        clip = self.object
        if self.request.POST.get("action") == "unpublish":
            # Non-destructive: drop from public surfaces, keep in collections.
            clip.visibility = Clip.Visibility.UNLISTED
            clip.save(update_fields=["visibility"])
        else:
            # The only full-destroy entry point (cascades links + cleans files).
            destroy_clip(clip)
        return HttpResponseRedirect(self.get_success_url())


# view to display a single users clips
def user_clips(request, username):
    user = get_object_or_404(User, username=username)
    clip_qs = (
        Clip.objects.filter(uploader=user)
        .select_related("uploader")
        .order_by("-date_uploaded")
    )
    page_obj = Paginator(clip_qs, PAGE_SIZE).get_page(request.GET.get("page"))
    context = {
        "user_object": user,
        "clips": page_obj,
        "page_obj": page_obj,
        "title": f"{user.username}'s Clips",
    }
    return render(request, "clips/user_clips.html", context)
