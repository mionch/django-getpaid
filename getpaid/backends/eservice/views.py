import HTMLParser
import logging

import six
from django.core.urlresolvers import reverse
from django.http import HttpResponse, HttpResponseRedirect
from django.http.response import HttpResponseBadRequest
from django.views.generic.base import View, RedirectView
from getpaid.backends.eservice import PaymentProcessor
from getpaid.models import Payment


html_parser = HTMLParser.HTMLParser()
logger = logging.getLogger('getpaid.backends.eservice')


class PendingView(View):
    """
    This view just redirects to standard backend success link for now, but will need to register that the payment is
    still under processing and has to be queried later.
    """

    def post(self, request, *args, **kwargs):
        if not PaymentProcessor.validate_hash(request):
            return HttpResponseBadRequest()

        payment_external_id = request.POST.get('OrderId')
        status = request.POST.get('mdStatus')
        payment = Payment.objects.filter(external_id=payment_external_id).first()
        logger.error(u"Payment %s still pending with status %s" % (payment, status))
        PaymentProcessor.pending_payment(payment.pk)
        return HttpResponseRedirect(reverse(PaymentProcessor.get_backend_setting('pending_url'),
                                            kwargs={'pk': payment.pk}))


class SuccessView(RedirectView):
    """
    This view just redirects to standard backend success link.
    """

    def post(self, request, *args, **kwargs):
        if not PaymentProcessor.validate_hash(request):
            return HttpResponseBadRequest()

        payment_external_id = request.POST.get('OrderId')
        status = request.POST.get('mdStatus')
        payment = Payment.objects.filter(external_id=payment_external_id).first()
        logger.error(u"Payment %s successful with status %s" % (payment, status))
        PaymentProcessor.accept_payment(payment.pk)
        return HttpResponseRedirect(reverse('getpaid-success-fallback', kwargs={'pk': payment.pk}))


class FailureView(RedirectView):
    """
    This view just redirects to standard backend failure link.
    """

    def post(self, request, *args, **kwargs):
        if not PaymentProcessor.validate_hash(request):
            return HttpResponseBadRequest()

        payment_external_id = request.POST.get('OrderId')
        status = request.POST.get('mdStatus')
        error_message = six.text_type(html_parser.unescape(request.POST.get('mdErrorMsg')))
        payment = Payment.objects.filter(external_id=payment_external_id).first()
        logger.error(u"Payment %s failed on backend error %s with status %s" % (payment, error_message, status))
        PaymentProcessor.payment_error(payment.pk)
        return HttpResponseRedirect(reverse('getpaid-failure-fallback', kwargs={'pk': payment.pk}))
