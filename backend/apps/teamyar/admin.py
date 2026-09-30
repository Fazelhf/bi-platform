from django.contrib import admin

from .models import LogEntry, Meeting, Phase, Task

admin.site.register([Phase, Task, Meeting, LogEntry])
