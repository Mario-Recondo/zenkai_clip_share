from django.urls import path

from . import views

urlpatterns = [
    path("", views.collection_list, name="collection-list"),
    path("create/", views.CollectionCreateView.as_view(), name="collection-create"),
    path("<int:pk>/", views.collection_detail, name="collection-detail"),
    path(
        "<int:pk>/delete/",
        views.CollectionDeleteView.as_view(),
        name="collection-delete",
    ),
    path("<int:pk>/upload/", views.collection_upload, name="collection-upload"),
    path("<int:pk>/add-clip/", views.collection_add_clip, name="collection-add-clip"),
    path(
        "<int:pk>/clips/<int:clip_pk>/remove/",
        views.collection_remove_clip,
        name="collection-remove-clip",
    ),
    path(
        "<int:pk>/clips/<int:clip_pk>/delete/",
        views.collection_delete_clip,
        name="collection-delete-clip",
    ),
]
