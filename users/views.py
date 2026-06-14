from django.shortcuts import render, redirect
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import UserRegistrationForm, AvatarUpdateForm
from .models import Profile


def register(request):
    if request.method == 'POST':
        # if the request is a POST, it means the form has been submitted
        form = UserRegistrationForm(request.POST)  # populate form with submitted data
        if form.is_valid():
            form.save()  # save the new user to the database
            username = form.cleaned_data.get('username')
            # could potentially add an account creation  success messege here

            return redirect('login')  # redirect to the login page after successful login
    else:
        # if request is a GET then I need to display an empty form
        form = UserRegistrationForm()
    return render(request, 'users/register.html', {'form': form, 'title': 'Register'})


@login_required
@require_POST
def avatar_update(request):
    """AJAX endpoint behind the account-menu "Change avatar" modal. Validates and
    saves the uploaded image, then returns the new URL so the client can swap the
    nav thumbnail live without a page reload."""
    profile_obj, _ = Profile.objects.get_or_create(user=request.user)
    form = AvatarUpdateForm(request.POST, request.FILES, instance=profile_obj)

    if form.is_valid():
        form.save()
        return JsonResponse({'url': profile_obj.profile_picture.url})

    errors = form.errors.get('profile_picture', ['Could not update avatar.'])
    return JsonResponse({'error': errors[0]}, status=400)


@login_required
def session_ping(request):
    """Keepalive hit by the idle-timeout JS while the user is active. The request
    itself is what matters: IdleLogoutMiddleware re-stamps last_activity on it,
    resetting the server-side inactivity clock. Returns a tiny JSON ack."""
    return JsonResponse({'ok': True})


@login_required
@require_POST
def session_timeout_logout(request):
    """Client-initiated logout when the idle countdown elapses with no response.
    POST-only and login-required so the endpoint can't show the inactivity notice
    without actually flushing an authenticated session."""
    logout(request)
    return redirect(f"{reverse('login')}?timeout=1")


class CustomLoginView(LoginView):
    template_name = 'users/login.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Login'
        return context


class CustomLogoutView(LogoutView):
    template_name = 'users/logout.html'
    next_page = 'login'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Logged Out'
        return context

