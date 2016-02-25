from django.conf.urls import patterns, url
from django.views.decorators.csrf import csrf_exempt

from getpaid.backends.saferpay.views import AssertPaymentView

urlpatterns = patterns('',
    url(r'^success/(?P<pk>\d+)/', AssertPaymentView.as_view(), name='getpaid-saferpay-success'),
    url(r'^failure/(?P<pk>\d+)/', AssertPaymentView.as_view(), name='getpaid-saferpay-failure'),
)
