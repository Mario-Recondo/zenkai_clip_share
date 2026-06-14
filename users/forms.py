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


class AvatarUpdateForm(forms.ModelForm):
    # 5 MB cap and an explicit image-type allowlist. ImageField already
    # confirms the upload is a decodable image; this adds the size/format
    # guardrails for the public avatar-upload endpoint.
    MAX_AVATAR_BYTES = 5 * 1024 * 1024
    ALLOWED_CONTENT_TYPES = {'image/jpeg', 'image/png', 'image/webp'}

    class Meta:
        model = Profile
        fields = ['profile_picture']

    def clean_profile_picture(self):
        image = self.cleaned_data.get('profile_picture')
        if not image:
            raise forms.ValidationError("Please choose an image.")

        if image.size > self.MAX_AVATAR_BYTES:
            raise forms.ValidationError("Image must be 5 MB or smaller.")

        content_type = getattr(image, 'content_type', None)
        if content_type and content_type not in self.ALLOWED_CONTENT_TYPES:
            raise forms.ValidationError("Use a JPEG, PNG, or WebP image.")

        return image
