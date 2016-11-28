import logging

import requests
import time

from decimal import Decimal
from django.core.exceptions import ImproperlyConfigured, SuspiciousOperation
from django.utils import six
from six.moves.urllib.request import Request, urlopen
from six.moves.urllib.parse import urlencode
from django.utils.translation import ugettext_lazy as _

from getpaid.backends import PaymentProcessorBase
from getpaid.utils import get_domain, build_absolute_uri

logger = logging.getLogger('getpaid.backends.saferpay')


class SaferpayApiError(Exception):
    pass


class PaymentProcessor(PaymentProcessorBase):
    BACKEND = u'getpaid.backends.saferpay'
    BACKEND_NAME = _(u'SaferPay')
    BACKEND_ACCEPTED_CURRENCY = (u'EUR', u'USD', u'GBP', u'CHF')
    BACKEND_LOGO_URL = u'getpaid/backends/saferpay/saferpay_logo.png'

    _GATEWAY_URL = u'https://www.saferpay.com/api/'
    _TEST_GATEWAY_URL = u'https://test.saferpay.com/api/'

    @classmethod
    def get_api_url(cls):
        return cls._GATEWAY_URL if not PaymentProcessor.get_backend_setting('test', False) else cls._TEST_GATEWAY_URL

    @classmethod
    def _post(cls, url, json_data):
        headers = {'Content-type': 'application/json; charset=utf-8', 'Accept': 'application/json'}

        request_id = u'rid{}'.format(int(time.time() * 1000))
        json_data['RequestHeader'] = {
            "SpecVersion": PaymentProcessor.get_backend_setting('api_version', '1.3'),
            "CustomerId": PaymentProcessor.get_backend_setting('customer_id'),
            "RequestId": request_id,
            "RetryIndicator": 0
        }

        response = requests.post(cls.get_api_url() + url, json=json_data, headers=headers,
                                 auth=(PaymentProcessor.get_backend_setting('api_username'),
                                       PaymentProcessor.get_backend_setting('api_password')))
        response_json = response.json()

        # verify that the request ID was not changed
        if response_json['ResponseHeader']['RequestId'] != request_id:
            raise SuspiciousOperation('RequestId does not match the response')

        if response.status_code != 200:
            error_message = 'Saferpay API error: status code {}, {}: {}. Details: {}. Transaction id:{}'.format(
                response.status_code, response_json['ErrorName'], response_json['ErrorMessage'],
                response_json.get('ErrorDetail', ''), response_json.get('TransactionId', 'None'))
            logger.warning(error_message)
            raise SaferpayApiError(error_message)
        return response.json()

    def generate_payment_id(self):
        order_id_field = PaymentProcessor.get_backend_setting('order_unique_id_field', 'id')
        order_id = getattr(self.payment.order, order_id_field)
        return six.text_type(u'{}'.format(order_id))

    def get_gateway_url(self, request):
        """
        Routes a payment to Gateway, should return URL for redirection.

        """
        url_data = {
            'domain': get_domain(request=request),
            'scheme': request.scheme,
            'reverse_kwargs': {'pk': self.payment.id}
        }

        call_json_data = {
            "TerminalId": PaymentProcessor.get_backend_setting('terminal_id'),
            "Payment": {
                "Amount": {
                    "Value": self.payment.amount,
                    "CurrencyCode":  self.payment.currency
                },
                "OrderId": self.payment.order.id,
                "Description": self.get_order_description(self.payment, self.payment.order),
            },
            "ReturnUrls": {
                "Success": build_absolute_uri('getpaid:saferpay:success', **url_data),
                "Fail": build_absolute_uri('getpaid:saferpay:failure', **url_data),
            }
        }

        recurring_field = PaymentProcessor.get_backend_setting('recurring_field', None)
        if recurring_field and getattr(self.payment.order, recurring_field, False):
            call_json_data["RecurringOptions"] = {"Initial": True}

        response_json = self._post('Payment/v1/PaymentPage/Initialize', call_json_data)
        self.payment.external_id = self._pack_external_id(response_json['Token'])

        gateway_url = response_json['RedirectUrl']
        return gateway_url, 'GET', {}

    @classmethod
    def update_payment_status(cls, payment):
        """
        Verifies the status of the payment and updates it.

        """
        token, transaction_id = cls._unpack_external_id(payment.external_id)
        call_json_data = {
            'Token': token
        }
        try:
            response_json = cls._post('Payment/v1/PaymentPage/Assert', call_json_data)
            try:
                status = response_json['Transaction']['Status']
                amount = response_json['Transaction']['Amount']
                transaction_id = response_json['Transaction']['Id']
                amount_currency = amount['CurrencyCode']
                amount_value = amount['Value']

                payment.external_id = cls._pack_external_id(token, transaction_id)

                if status in ['AUTHORIZED', 'CAPTURED']:
                    logger.info('Payment {} accepted with status {} and amount {} {}.'.format(
                        payment.id, status, amount_value, amount_currency))
                    payment.on_success(Decimal(amount_value))
                    return True
                logger.info('Payment {} accepted with status {} and amount {} {} but status is neither authorized '
                            'or captured, so rejecting.'.format(payment.id, status, amount_value, amount_currency))
            except (KeyError, ValueError) as e:
                logger.info('Payment {} not rejected, but status assert did not return all required '
                            'information.'.format(payment.currency))
        except SaferpayApiError as e:
            logger.info('Payment {} rejected. Info: {}'.format(payment.id, e))
        payment.on_failure()
        return False

    @staticmethod
    def _pack_external_id(token, transaction_id=''):
        return u'{}_{}'.format(token, transaction_id)

    @staticmethod
    def _unpack_external_id(external_id):
        token, transaction_id = external_id.split('_')
        transaction_id = transaction_id or None
        return token, transaction_id
