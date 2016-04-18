from django.conf.urls import patterns, url
from django.views.decorators.csrf import csrf_exempt
from getpaid.backends.eservice.views import PendingView, SuccessView, FailureView


urlpatterns = patterns('',
    url(r'^pending/$', csrf_exempt(PendingView.as_view()), name='getpaid-eservice-pending'),
    url(r'^success/$', csrf_exempt(SuccessView.as_view()), name='getpaid-eservice-success'),
    url(r'^failure/$', csrf_exempt(FailureView.as_view()), name='getpaid-eservice-failure'),
)
