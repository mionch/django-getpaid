# -*- coding: utf-8 -*-
import base64
import hashlib
import logging

from __builtin__ import getattr
from xml.etree import ElementTree

import requests
from lxml import etree

from django.apps import apps
from django.utils import six
from django.utils.translation import ugettext_lazy as _
from six.moves.urllib.parse import urlencode
from six.moves.urllib.request import Request, urlopen

from getpaid.backends.eservice.tasks import get_payment_status_task

try:
    from django.db.transaction import commit_on_success_or_atomic
except ImportError:
    from django.db.transaction import atomic as commit_on_success_or_atomic

from getpaid import signals
from getpaid.backends import PaymentProcessorBase
# from getpaid.backends.payu.tasks import get_payment_status_task, accept_payment
from getpaid.utils import build_absolute_uri, get_domain

logger = logging.getLogger('getpaid.backends.eservice')


class EServiceCurrency:
    type_map = {
        'PLN': 985,
        'EUR': 978,
        'USD': 840,
        'GBP': 826,
        'CHF': 756,
        'DKK': 208,
        'CAD': 124,
        'NOK': 578,
        'SEK': 752,
        'RUB': 643,
        'LTL': 440,
        'RON': 946,
        'CZK': 203,
        'JPY': 392,
        'HUF': 348,
        'HRK': 191,
        'UAH': 980,
        'TRY': 949,
    }

    @classmethod
    def get_by_name(cls, currency_name):
        return cls.type_map.get(currency_name)


class EserviceTransactionStatus:
    DECLINED = 'D'
    PRE_APPROVED = 'A'
    APPROVED = 'C'
    DEPOSITED = 'S'
    PENDING = 'PN'
    CANCELED = 'V'

    SUCCESS_STATUSES = [APPROVED, DEPOSITED]
    ERROR_STATUSES = [CANCELED]


class PaymentProcessor(PaymentProcessorBase):
    BACKEND = u'getpaid.backends.eservice'
    BACKEND_NAME = _(u'EService')
    BACKEND_ACCEPTED_CURRENCY = (u'PLN',)
    BACKEND_LOGO_URL = u'getpaid/backends/eservice/eservice_logo.png'

    _TEST_GATEWAY_URL = u'https://testvpos.eservice.com.pl/'
    _GATEWAY_URL = u'https://pay.eservice.com.pl/'
    _API_URL = u'https://pay.eservice.com.pl:19445/fim/api'
    _ACCEPTED_LANGS = (u'pl', u'en')

    def generate_payment_id(self):
        order_id_field = PaymentProcessor.get_backend_setting('order_unique_id_field', 'id')
        order_id = getattr(self.payment.order, order_id_field)
        return six.text_type(u'{}{}'.format(order_id, self.payment.pk))

    @staticmethod
    def validate_hash(request):
        hashparams = request.POST.get('HASHPARAMS')

        param_list = [param for param in hashparams.split(':') if param]
        prehash_values = [request.POST.get(param_name) for param_name in param_list]

        # hash_data = ''.join([value for value in prehash_values if value])

        # FIXME - this is not mentioned in the documentation, however in case of an error, some params are not
        # included in the hash received from the eservice backend causing the hash to validate improperly
        # - thus we are  using  the hashparamsval parameter from the request, which appears to have the proper value
        #  of the hash_data parameters
        hash_data = request.POST.get('HASHPARAMSVAL')

        store_key = six.text_type(PaymentProcessor.get_backend_setting('password'))
        calculated_hash = base64.b64encode(hashlib.sha1(hash_data + store_key).digest())

        match = calculated_hash == request.POST.get('HASH')
        if not match:
            logger.warning('Malformed hash value for transaction, aborting')
        return match

    def get_gateway_url(self, request):
        """
        Routes a payment to Gateway, should return URL for redirection.

        """

        self.payment.external_id = self.generate_payment_id()
        params = {
            'ClientId': six.text_type(PaymentProcessor.get_backend_setting('client_id')),
            'Password': six.text_type(PaymentProcessor.get_backend_setting('password')),
            'OrderId': self.payment.external_id,
            'Total': self.payment.amount,
            'Currency': EServiceCurrency.get_by_name(self.payment.currency)
        }

        token = self.get_token(params)
        params.pop('Password')

        if token is None:
            # TODO Handle broken payment
            logger.error('No token could be retrieved for the payment')

        params['Token'] = six.text_type(token)

        user_data = {
            'lang': None,
        }

        signals.user_data_query.send(sender=None, order=self.payment.order, user_data=user_data)

        if user_data['lang'] and user_data['lang'].lower() in PaymentProcessor._ACCEPTED_LANGS:
            params['lang'] = user_data['lang'].lower()
        elif PaymentProcessor.get_backend_setting('lang', False) and \
                PaymentProcessor.get_backend_setting('lang').lower() in PaymentProcessor._ACCEPTED_LANGS:
            params['lang'] = six.text_type(PaymentProcessor.get_backend_setting('lang').lower())

        url_data = {
            'domain': get_domain(request=request),
            'scheme': request.scheme
        }
        params['okUrl'] = build_absolute_uri('getpaid-eservice-success',  **url_data)
        params['failUrl'] = build_absolute_uri('getpaid-eservice-failure', **url_data)
        params['pendingUrl'] = build_absolute_uri('getpaid-eservice-pending', **url_data)

        params['StoreType'] = PaymentProcessor.get_backend_setting('store_type')
        params['TranType'] = u'Auth'

        params['ConsumerName'] = user_data.get('first_name', u'')
        params['ConsumerSurname'] = user_data.get('last_name', u'')

        params['ShipToName'] = user_data.get('shipping_country', u'')
        params['ShipToPostalCode'] = user_data.get('shipping_zip_code', u'')
        params['ShipToStreet1'] = user_data.get('shipping_address', u'')
        params['ShipToCity'] = user_data.get('shipping_city', u'')
        params['ShipToCountry'] = u'PL'

        params['BillToName'] = user_data.get('name') or u'{} {}'.format(user_data.get('first_name', u''),
                                                                        user_data.get('last_name', u''))
        params['BillToPostalCode'] = user_data.get('adress_zip_code', u'')
        params['BillToStreet1'] = user_data.get('adress', u'')
        params['BillToCity'] = user_data.get('address_city', u'')
        params['BillToCountry'] = user_data.get('address_country', u'')

        logger.info(u'New payment using GET: %s' % params)
        for key in params.keys():
            params[key] = six.text_type(params[key]).encode('utf-8')
        return self._GATEWAY_URL + 'fim/eservicegate?' + urlencode(params), 'GET', {}

    def get_token(self, params):
        data = six.text_type(urlencode(params)).encode('utf-8')
        url = self._GATEWAY_URL + 'pg/token'
        request = Request(url, data)
        response = urlopen(request)
        response_data = self._unpack_response_data(response.read().decode('utf-8'))

        message = response_data.get('msg', '')
        if response_data.get('status') == 'ok':
            if not message:
                logger.error(u'Get token method returned OK status, but no token was provided')
            else:
                return message
        logger.error(u'Get token method ERROR. Message: {}'.format(message))
        return None

    def check_order_status(self):
        xml_body = etree.Element("CC5Request")
        etree.SubElement(xml_body, "Name").text = six.text_type(PaymentProcessor.get_backend_setting('api_user'))
        etree.SubElement(xml_body, "Password").text = six.text_type(PaymentProcessor.get_backend_setting('api_password'))
        etree.SubElement(xml_body, "ClientId").text = six.text_type(PaymentProcessor.get_backend_setting('client_id'))
        etree.SubElement(xml_body, "OrderId").text = str(self.payment.external_id)
        extra_options = etree.SubElement(xml_body, "Extra")
        etree.SubElement(extra_options, "ORDERSTATUS").text = 'QUERY'
        contents = etree.tostring(xml_body, encoding='utf-8')

        response = requests.post(self._API_URL, data=contents).text

        xml_response = ElementTree.fromstring(response)
        ret_code_element = xml_response.find('Extra/PROC_RET_CD')
        ret_code = ret_code_element.text if ret_code_element is not None else None
        if ret_code != '00':
            logger.warning('Payment {} not processed yet'.format(self.payment.id))
            return False

        status_element = xml_response.find('Extra/TRANS_STAT')
        status = status_element.text if status_element is not None else None
        logger.warning('Received status {} for payment {}'.format(status, self.payment.id))
        if status in EserviceTransactionStatus.SUCCESS_STATUSES:
            logger.warning('Processing success for payment {}'.format(self.payment.id))
            self.payment.on_success()
            return True
        elif status in EserviceTransactionStatus.ERROR_STATUSES:
            logger.warning('Processing failure for payment {}'.format(self.payment.id))
            self.payment.on_failure()
            return True


    @staticmethod
    def accept_payment(payment_id):
        """
        Payment was confirmed.
        """
        Payment = apps.get_model('getpaid', 'Payment')
        with commit_on_success_or_atomic():
            payment = Payment.objects.get(id=payment_id)
            return payment.on_success()

    @staticmethod
    def pending_payment(payment_id=None):
        """
        Payment was accepted into the queue for processing.
        """
        Payment = apps.get_model('getpaid', 'Payment')
        with commit_on_success_or_atomic():
            payment = Payment.objects.get(id=payment_id)
            payment.change_status('in_progress')
        get_payment_status_task.delay(payment_id)


    @staticmethod
    def payment_error(payment_id=None):
        """
        Payment was cancelled.
        """
        Payment = apps.get_model('getpaid', 'Payment')
        with commit_on_success_or_atomic():
            payment = Payment.objects.get(id=payment_id)
            payment.on_failure()

    @staticmethod
    def _unpack_response_data(data):
        entries = data.split('&')
        unpacked_data = {}
        for entry in entries:
            name, value = entry.split('=')
            unpacked_data[name] = value
        return unpacked_data