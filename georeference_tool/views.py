from django.shortcuts import render


def home(request):
    """Home page view"""
    context = {
        "page_title": "Home",
    }
    return render(request, "home.html", context)
