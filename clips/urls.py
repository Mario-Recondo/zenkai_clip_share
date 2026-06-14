from django.urls import path

from . import views

urlpatterns = [
    path("home/", views.clip_list, name="clip-list"),
    path("create/", views.ClipCreateView.as_view(), name="clip-create"),
    path("<int:pk>/", views.clip_detail, name="clip-detail"),
    path("<int:pk>/status/", views.clip_status, name="clip-status"),
    path("<int:pk>/delete/", views.ClipDeleteView.as_view(), name="clip-delete"),
    path("users/<str:username>/", views.user_clips, name="user-clips"),
]
