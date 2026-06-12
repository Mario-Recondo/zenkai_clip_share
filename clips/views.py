from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView

from .forms import ClipCreateForm
from .models import Clip
from .services import enqueue_transcode

PAGE_SIZE = 12


# Create your views here.
@login_required
def clip_list(request):
    # select_related avoids an N+1 on clip.uploader.username (Flaw #4)
    clip_qs = Clip.objects.select_related('uploader').order_by('-date_uploaded')
    query = request.GET.get('q', '').strip()
    if query:
        clip_qs = clip_qs.filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(uploader__username__icontains=query)
        )
    page_obj = Paginator(clip_qs, PAGE_SIZE).get_page(request.GET.get('page'))
    context = {
        'clips': page_obj,
        'page_obj': page_obj,
        'query': query,
        'title': f'Search: {query}' if query else 'Recent Clips',
    }
    return render(request, 'clips/clip_list.html', context)


def clip_detail(request, pk):
    clip = get_object_or_404(Clip.objects.select_related('uploader'), pk=pk)
    return render(request, 'clips/clip_detail.html', {'clip': clip, 'title': clip.title})


def clip_status(request, pk):
    """Tiny JSON endpoint polled by the frontend while a clip transcodes."""
    clip = get_object_or_404(Clip.objects.only('status', 'thumbnail'), pk=pk)
    return JsonResponse({
        'status': clip.status,
        'thumbnail_url': clip.thumbnail.url if clip.thumbnail else None,
    })

# class based view for uploading clips
class ClipCreateView(LoginRequiredMixin, CreateView):
    model = Clip
    form_class = ClipCreateForm
    template_name = 'clips/clip_create.html'
    # Back to the grid, where the new clip appears first with a live
    # "Processing" badge (see static/js/clip-status.js).
    success_url = reverse_lazy('clip-list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Upload a Clip'
        return context

    def form_valid(self, form):
        form.instance.uploader = self.request.user
        response = super().form_valid(form)
        # Hand transcoding off to the worker instead of blocking the request (Flaw #1)
        enqueue_transcode(self.object)
        return response

class ClipDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    model = Clip
    template_name = 'clips/clip_confirm_delete.html'
    success_url = reverse_lazy('clip-list')

    def test_func(self):
        # Only the uploader may delete their clip (403 otherwise).
        return self.get_object().uploader == self.request.user

    def form_valid(self, form):
        # Capture file refs before the row disappears, then clean up storage.
        # Row first so a storage hiccup can only orphan files, never resurrect
        # a deleted clip.
        clip = self.object
        files = [clip.video_file, clip.converted_video_file, clip.thumbnail]
        response = super().form_valid(form)
        for f in files:
            if f:
                f.delete(save=False)
        return response


# view to display a single users clips
def user_clips(request, username):
    user = get_object_or_404(User, username=username)
    clip_qs = (
        Clip.objects.filter(uploader=user)
        .select_related('uploader')
        .order_by('-date_uploaded')
    )
    page_obj = Paginator(clip_qs, PAGE_SIZE).get_page(request.GET.get('page'))
    context = {
        'user_object': user,
        'clips': page_obj,
        'page_obj': page_obj,
        'title': f"{user.username}'s Clips",
    }
    return render(request, 'clips/user_clips.html', context)
