from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import CreateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User

from .models import Clip
from .forms import ClipCreateForm
from django.contrib.auth.decorators import login_required


# Create your views here.
@login_required
def clip_list(request):
    clips = Clip.objects.all().order_by('date_uploaded')
    context = {
        'clips': clips,
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
        return super().form_valid(form)

# view to display a single users clips
def user_clips(request, username):
    user = get_object_or_404(User, username=username)
    clips = Clip.objects.filter(uploader=user).order_by('-date_uploaded')
    context = {
        'user_object': user,
        'clips': clips,
        'title': f"{user.username}'s Clips",
    }
    return render(request, 'clips/user_clips.html', context)