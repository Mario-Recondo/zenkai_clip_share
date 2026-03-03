from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User  # built in user model
from .models import Profile


# Using Django built in user form creation
class UserRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)  # Adds an email field

    class Meta:
        model = User  # tells django to use the built-in user model with the fields below
        fields = ['username', 'email', 'password1', 'password2']

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("This email is already in use.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
        return user


class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ['profile_picture', 'bio']


class UserUpdateForm(forms.ModelForm):
    email = forms.EmailField()

    class Meta:
        model = User
        fields = ['username', 'email']
