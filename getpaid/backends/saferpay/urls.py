from django.conf.urls import patterns, url

from getpaid.backends.saferpay.views import AssertPaymentView

urlpatterns = patterns('',
    url(r'^success/(?P<pk>\d+)/', AssertPaymentView.as_view(), name='success'),
    url(r'^failure/(?P<pk>\d+)/', AssertPaymentView.as_view(), name='failure'),
)
