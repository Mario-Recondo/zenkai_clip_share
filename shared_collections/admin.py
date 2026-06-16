from django.contrib import admin

from .models import Collection, CollectionClip, CollectionMembership


class CollectionMembershipInline(admin.TabularInline):
    model = CollectionMembership
    extra = 0


class CollectionClipInline(admin.TabularInline):
    model = CollectionClip
    extra = 0
    raw_id_fields = ("clip", "added_by")


@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "created_at")
    search_fields = ("name", "owner__username")
    inlines = (CollectionMembershipInline, CollectionClipInline)


@admin.register(CollectionMembership)
class CollectionMembershipAdmin(admin.ModelAdmin):
    list_display = ("collection", "user", "status", "allow_owner_delete", "joined_at")
    list_filter = ("status", "allow_owner_delete")
    search_fields = ("collection__name", "user__username")


@admin.register(CollectionClip)
class CollectionClipAdmin(admin.ModelAdmin):
    list_display = ("collection", "clip", "added_by", "added_at")
    search_fields = ("collection__name", "clip__title", "added_by__username")
    raw_id_fields = ("clip", "added_by")
