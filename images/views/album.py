import json

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import models
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from django.contrib.auth.models import User


from ..models import (
    Album,
    AlbumImage,
    Image,
)


def edit_album(request, album_id):
    """Edit album title and description (owner only)"""
    if not request.user.is_authenticated:
        return redirect("login")

    album = get_object_or_404(Album, id=album_id)

    # Check that the user is the owner
    if album.owner != request.user:
        raise Http404("Album not found")

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()

        # Validate title
        if not title:
            messages.error(request, "Album title is required.")
            return render(
                request,
                "images/album_edit.html",
                {
                    "album": album,
                    "profile_user": album.owner,
                    "display_name": album.owner.get_display_name()
                    if hasattr(album.owner, "get_display_name")
                    else album.owner.username,
                },
            )

        if len(title) > 500:
            messages.error(request, "Album title must be 500 characters or less.")
            return render(
                request,
                "images/album_edit.html",
                {
                    "album": album,
                    "profile_user": album.owner,
                    "display_name": album.owner.get_display_name()
                    if hasattr(album.owner, "get_display_name")
                    else album.owner.username,
                },
            )

        # Update album
        album.title = title
        album.description = description
        album.map_mode = "map_mode" in request.POST
        album.save(update_fields=["title", "description", "map_mode"])

        messages.success(request, "Album updated successfully.")
        return redirect(
            "images:album_detail",
            display_name=album.owner.get_display_name()
            if hasattr(album.owner, "get_display_name")
            else album.owner.username,
            album_id=album.id,
        )

    # GET request - display the edit form
    display_name = (
        album.owner.get_display_name()
        if hasattr(album.owner, "get_display_name")
        else album.owner.username
    )

    context = {
        "album": album,
        "profile_user": album.owner,
        "display_name": display_name,
    }

    return render(request, "images/album_edit.html", context)


def delete_album(request, album_id):
    """Delete album (owner only) - confirmation page"""
    if not request.user.is_authenticated:
        return redirect("login")

    album = get_object_or_404(Album, id=album_id)

    # Check that the user is the owner
    if album.owner != request.user:
        raise Http404("Album not found")

    if request.method == "POST":
        # Confirm deletion
        album_title = album.title
        # Get the display name (OSM username) for the redirect
        # Special case: hardcoded_admin needs to use the Django username
        if album.owner.username == "hardcoded_admin":
            album_owner_username = "hardcoded_admin"
        else:
            album_owner_username = (
                album.owner.get_display_name()
                if hasattr(album.owner, "get_display_name")
                else album.owner.username
            )
        album.delete()
        messages.success(request, f"Album '{album_title}' has been deleted.")
        return redirect("user_albums_list", username=album_owner_username)

    # GET request - display confirmation page
    display_name = (
        album.owner.get_display_name()
        if hasattr(album.owner, "get_display_name")
        else album.owner.username
    )

    context = {
        "album": album,
        "profile_user": album.owner,
        "display_name": display_name,
    }

    return render(request, "images/album_delete_confirm.html", context)


@require_http_methods(["GET"])
def user_albums_api(request):
    """API endpoint to get user's albums as JSON"""
    if not request.user.is_authenticated:
        return JsonResponse({"albums": []})

    image_id = request.GET.get("image_id")

    albums = Album.objects.filter(owner=request.user).order_by("-created_at")

    albums_data = []
    for album in albums:
        album_dict = {"id": album.id, "title": album.title, "has_image": False}
        # Check if the image is in this album
        if image_id:
            album_dict["has_image"] = album.images.filter(id=image_id).exists()
        albums_data.append(album_dict)

    return JsonResponse({"albums": albums_data})


@require_http_methods(["POST"])
def add_image_to_album(request):
    """API endpoint to add an image to an existing album"""
    if not request.user.is_authenticated:
        return JsonResponse(
            {"success": False, "error": "Not authenticated"}, status=401
        )

    try:
        data = json.loads(request.body)
        image_id = data.get("image_id")
        album_id = data.get("album_id")

        if not image_id or not album_id:
            return JsonResponse(
                {"success": False, "error": "Missing image_id or album_id"}, status=400
            )

        image = get_object_or_404(Image, id=image_id)
        album = get_object_or_404(Album, id=album_id, owner=request.user)

        # Get the next order value
        max_order = album.album_images.aggregate(models.Max("order"))["order__max"] or 0
        next_order = max_order + 1

        # Add image to album
        album_image, created = AlbumImage.objects.get_or_create(
            album=album, image=image, defaults={"order": next_order}
        )

        if created:
            return JsonResponse(
                {"success": True, "message": f"Image added to album '{album.title}'"}
            )
        else:
            return JsonResponse(
                {"success": True, "message": f"Image already in album '{album.title}'"}
            )

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


@require_http_methods(["POST"])
def create_and_add_to_album(request):
    """API endpoint to create a new album and add an image to it"""
    if not request.user.is_authenticated:
        return JsonResponse(
            {"success": False, "error": "Not authenticated"}, status=401
        )

    try:
        data = json.loads(request.body)
        image_id = data.get("image_id")
        album_title = data.get("album_title", "").strip()
        album_description = data.get("album_description", "").strip()
        album_public = data.get("album_public", False)

        if not image_id:
            return JsonResponse(
                {"success": False, "error": "Missing image_id"}, status=400
            )

        if not album_title:
            return JsonResponse(
                {"success": False, "error": "Album title is required"}, status=400
            )

        image = get_object_or_404(Image, id=image_id)

        # Create the album
        album = Album.objects.create(
            owner=request.user,
            title=album_title,
            description=album_description,
            public=album_public,
        )

        # Add image to album
        AlbumImage.objects.create(album=album, image=image, order=1)

        return JsonResponse(
            {
                "success": True,
                "message": f"Album '{album.title}' created and image added",
                "album_id": album.id,
            }
        )

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


@require_http_methods(["POST"])
def remove_image_from_album(request):
    """API endpoint to remove an image from an album"""
    if not request.user.is_authenticated:
        return JsonResponse(
            {"success": False, "error": "Not authenticated"}, status=401
        )

    try:
        data = json.loads(request.body)
        image_id = data.get("image_id")
        album_id = data.get("album_id")

        if not image_id or not album_id:
            return JsonResponse(
                {"success": False, "error": "Missing image_id or album_id"}, status=400
            )

        image = get_object_or_404(Image, id=image_id)
        album = get_object_or_404(Album, id=album_id, owner=request.user)

        # Remove image from album
        deleted_count, _ = AlbumImage.objects.filter(album=album, image=image).delete()

        if deleted_count > 0:
            return JsonResponse(
                {
                    "success": True,
                    "message": f"Image removed from album '{album.title}'",
                }
            )
        else:
            return JsonResponse(
                {"success": False, "error": "Image was not in this album"}, status=400
            )

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


def album_detail(request, display_name, album_id):
    """Display a specific album with its images"""

    # Look up user by display name (first_name for OSM users or username)
    # Try first_name first (OSM username), then fall back to username
    user = get_object_or_404(User, first_name=display_name)
    if not user:
        user = get_object_or_404(User, username=display_name)
    album = get_object_or_404(Album, id=album_id, owner=user)

    # Check permissions - only show if public or user is viewing their own
    if not album.public and (not request.user.is_authenticated or request.user != user):
        raise Http404("Album not found")

    # Get images in album order
    album_images = album.album_images.select_related("image").order_by("order")

    # Extract the actual Image objects from AlbumImage objects
    images = [ai.image for ai in album_images]

    # Calculate pending images count for the georeference button
    pending_images = sum(1 for image in images if not image.is_georeferenced)

    # Calculate georeferenced images count for map display
    georeferenced_images = sum(1 for image in images if image.is_georeferenced)

    # Paginate images for browsing
    paginator = Paginator(images, 24)  # 24 images per page for grid layout
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Check if map_mode is available (handle migration period)
    album_map_mode = getattr(album, "map_mode", False)

    display_name = (
        user.get_display_name() if hasattr(user, "get_display_name") else user.username
    )
    is_owner = request.user.is_authenticated and request.user == user

    context = {
        "album": album,
        "page_obj": page_obj,
        "profile_user": user,
        "display_name": display_name,
        "is_owner": is_owner,
        "pending_images": pending_images,
        "georeferenced_images": georeferenced_images,
        "album_map_mode": album_map_mode,
    }
    return render(request, "images/album_detail.html", context)


@require_http_methods(["POST"])
def toggle_album_public(request, album_id):
    """Toggle album public/private status (owner only)"""

    if not request.user.is_authenticated:
        return JsonResponse(
            {"success": False, "error": "Authentication required"}, status=401
        )

    try:
        data = json.loads(request.body)
        new_public_status = data.get("public", True)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    try:
        album = get_object_or_404(Album, id=album_id)
    except:
        return JsonResponse({"success": False, "error": "Album not found"}, status=404)

    # Check that the user is the owner
    if album.owner != request.user:
        return JsonResponse(
            {
                "success": False,
                "error": "You don't have permission to modify this album",
            },
            status=403,
        )

    # Update the public status
    album.public = new_public_status
    album.save()

    return JsonResponse({"success": True, "public": album.public})
