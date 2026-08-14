from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views, views_chat, views_work

router = DefaultRouter()
router.register("letters", views.LetterViewSet, basename="letter")
router.register("letter-tags", views.LetterTagViewSet, basename="letter-tag")
router.register("projects", views_work.ProjectViewSet, basename="project")
router.register("tasks", views_work.TaskViewSet, basename="task")
router.register("task-groups", views_work.TaskGroupViewSet, basename="task-group")
router.register("task-tags", views_work.TaskTagViewSet, basename="task-tag")
router.register("chat-groups", views_chat.ChatGroupViewSet, basename="chat-group")

urlpatterns = [
    path("", include(router.urls)),
    path("mailbox/", views.MailboxView.as_view(), name="office-mailbox"),
    path("people/", views.OfficePeopleView.as_view(), name="office-people"),
    path("task-box/", views_work.TaskBoxView.as_view(), name="office-task-box"),
    path("workbench/", views_work.WorkbenchView.as_view(), name="office-workbench"),
    path("chat/", views_chat.ChatOverviewView.as_view(), name="office-chat"),
    path(
        "chat/messages/<int:pk>/",
        views_chat.MessageExtrasView.as_view(),
        name="office-message-extras",
    ),
]
