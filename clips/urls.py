from django.urls import path

from . import views

urlpatterns = [
    path('home/', views.clip_list, name='clip-list'),
    path('create/', views.ClipCreateView.as_view(), name='clip-create'),
    path('users/<str:username>/', views.user_clips, name='user-clips')

]