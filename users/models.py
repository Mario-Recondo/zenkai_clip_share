from django.db import models
from django.contrib.auth.models import User


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    # Blank when the user hasn't uploaded one; templates fall back to an
    # initial-letter badge (see templates/includes/avatar.html).
    profile_picture = models.ImageField(upload_to='profile_pics', blank=True, null=True)

    def __str__(self):
        return f'{self.user.username}Profile'
