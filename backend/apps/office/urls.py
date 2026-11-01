from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views, views_calendar, views_chat, views_work

router = DefaultRouter()
router.register("letters", views.LetterViewSet, basename="letter")
router.register("letter-tags", views.LetterTagViewSet, basename="letter-tag")
router.register("projects", views_work.ProjectViewSet, basename="project")
router.register("tasks", views_work.TaskViewSet, basename="task")
router.register("task-groups", views_work.TaskGroupViewSet, basename="task-group")
router.register("task-tags", views_work.TaskTagViewSet, basename="task-tag")
router.register("chat-groups", views_chat.ChatGroupViewSet, basename="chat-group")
router.register("calendar/events", views_calendar.EventViewSet, basename="calendar-event")
router.register("calendar/holidays", views_calendar.HolidayViewSet, basename="calendar-holiday")

urlpatterns = [
    path("", include(router.urls)),
    path("mailbox/", views.MailboxView.as_view(), name="office-mailbox"),
    path("people/", views.OfficePeopleView.as_view(), name="office-people"),
    path("task-box/", views_work.TaskBoxView.as_view(), name="office-task-box"),
    path("workbench/", views_work.WorkbenchView.as_view(), name="office-workbench"),
    path("chat/", views_chat.ChatOverviewView.as_view(), name="office-chat"),
    path("calendar/calendars/", views_calendar.CalendarListView.as_view(), name="office-calendars"),
    path("calendar/month/", views_calendar.MonthView.as_view(), name="office-calendar-month"),
    path("calendar/workweek/", views_calendar.WorkWeekView.as_view(), name="office-workweek"),
    path(
        "chat/messages/<int:pk>/",
        views_chat.MessageExtrasView.as_view(),
        name="office-message-extras",
    ),
]
