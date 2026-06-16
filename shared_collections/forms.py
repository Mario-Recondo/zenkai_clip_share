from django import forms

from .models import Collection


class CollectionForm(forms.ModelForm):
    """Create / edit a collection's basic details (name + description)."""

    class Meta:
        model = Collection
        fields = ["name", "description"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }
