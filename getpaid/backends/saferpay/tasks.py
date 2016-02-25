import logging
from celery.task.base import get_task_logger, task
from django.apps import apps


logger = logging.getLogger('getpaid.backends.saferpay')
task_logger = get_task_logger('getpaid.backends.saferpay')
