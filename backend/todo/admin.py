from django.contrib import admin

# Register your models here.
from .models import Todo


class TodoAdmin(admin.ModelAdmin):
    list_display = ('user_context', 'assist_context')


admin.site.register(Todo, TodoAdmin)
