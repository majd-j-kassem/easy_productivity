from django.core.exceptions import PermissionDenied


class StaffOnlyCMS:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info.startswith("/cms/") and request.user.is_authenticated and not request.user.is_staff:
            raise PermissionDenied
        return self.get_response(request)
