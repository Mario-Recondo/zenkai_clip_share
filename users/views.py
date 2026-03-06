from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView

from clips.models import Clip
from .forms import UserRegistrationForm, ProfileUpdateForm, UserUpdateForm
from .models import Profile


# Create views here.
@login_required  # decorator that ensures that logged-in users can access this view
def dashboard(request):
    user_clips = Clip.objects.filter(uploader=request.user).order_by('-date_uploaded')
    context = {
        'clips': user_clips,
        'title': 'Dashboard',
    }
    # user object is available in the template automatically if users can access this view
    return render(request, 'users/dashboard.html', context)


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
def profile(request):
    # Ensure the user always has a Profile instance
    profile_obj, _ = Profile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        u_form = UserUpdateForm(request.POST, instance=request.user)
        p_form = ProfileUpdateForm(request.POST, request.FILES, instance=profile_obj)

        if u_form.is_valid() and p_form.is_valid():
            u_form.save()
            p_form.save()
            return redirect('profile')

    else:
        #  for GET request, creates form instance with existing data
        u_form = UserUpdateForm(instance=request.user)
        p_form = ProfileUpdateForm(instance=profile_obj)

    context = {
        'u_form': u_form,
        'p_form': p_form,
        'title': f"{request.user.username}'s Profile",
    }
    return render(request, 'users/profile.html', context)


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

