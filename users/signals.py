from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile


@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    """
    Ensure every User has an associated Profile.
    """
    if created:
        Profile.objects.create(user=instance)
    else:
        # For existing users, make sure a profile exists.
        Profile.objects.get_or_create(user=instance)

