from django.db import models

# Create your models here.


class Todo(models.Model):
    user_context = models.TextField()
    assist_context = models.TextField()

    def _str_(self):
        return self.user_context
