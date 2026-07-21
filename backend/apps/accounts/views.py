from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class MeView(APIView):
    """The current user's identity + capabilities, for role-aware UI."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        return Response(
            {
                "username": u.get_username(),
                "display_name_fa": u.display_name_fa,
                "role": u.role,
                "department": u.department,
                "is_superuser": u.is_superuser,
                "can_enter_data": u.can_enter_data,
                "can_approve": u.can_approve,
            }
        )
