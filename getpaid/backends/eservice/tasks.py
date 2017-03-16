import logging
from celery.task.base import get_task_logger, task
from django.apps import apps


logger = logging.getLogger('getpaid.backends.eservice')
task_logger = get_task_logger('getpaid.backends.eservice')


@task(bind=True, max_retries=50, default_retry_delay=2*60)
def get_payment_status_task(self, payment_id, retry=True):
    logger.warning('Checking status for payment pk=%s', payment_id)
    Payment = apps.get_model('getpaid', 'Payment')
    try:
        payment = Payment.objects.get(pk=int(payment_id))
    except Payment.DoesNotExist:
        logger.error('Payment does not exist pk=%s', payment_id)
        return
    from getpaid.backends.eservice import PaymentProcessor
    processor = PaymentProcessor(payment)
    if not processor.check_order_status() and retry:
        logger.warning('Checking status for payment pk=%s not processed - retrying', payment_id)
        self.retry()
