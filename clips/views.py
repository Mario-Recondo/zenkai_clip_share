from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy
from django.views.generic import CreateView

from .forms import ClipCreateForm
from .models import Clip
from .services import enqueue_transcode

PAGE_SIZE = 12


# Create your views here.
@login_required
def clip_list(request):
    # select_related avoids an N+1 on clip.uploader.username (Flaw #4)
    clip_qs = Clip.objects.select_related('uploader').order_by('-date_uploaded')
    page_obj = Paginator(clip_qs, PAGE_SIZE).get_page(request.GET.get('page'))
    context = {
        'clips': page_obj,
        'page_obj': page_obj,
        'title': 'Recent Clips',
    }
    return render(request, 'clips/clip_list.html', context)

# class based view for uploading clips
class ClipCreateView(LoginRequiredMixin, CreateView):
    model = Clip
    form_class = ClipCreateForm
    template_name = 'clips/clip_create.html'
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
