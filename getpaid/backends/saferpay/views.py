import logging

from django.shortcuts import redirect, get_object_or_404
from django.views.generic.base import View

from getpaid.backends.saferpay import PaymentProcessor
from getpaid.models import Payment


class AssertPaymentView(View):
    def get(self, request, *args, **kwargs):
        payment = get_object_or_404(Payment, pk=kwargs.get('pk'))
        if PaymentProcessor.update_payment_status(payment):
            return redirect('getpaid-success-fallback', pk=payment.pk)
        return redirect('getpaid-failure-fallback', pk=payment.pk)
