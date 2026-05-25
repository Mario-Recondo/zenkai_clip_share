from django import forms

from .models import Clip


class ClipCreateForm(forms.ModelForm):
    class Meta:
        model = Clip
        fields = ['title', 'description', 'video_file']