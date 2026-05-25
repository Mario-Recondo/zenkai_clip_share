from django.urls import path
from django.views.generic import RedirectView

from . import views

urlpatterns = [
    path(
        'dashboard/',
        RedirectView.as_view(pattern_name='clip-list', permanent=False),
        name='dashboard',
    ),
    path('register/', views.register, name='register'),
    path('profile/', views.profile, name='profile'),
]
