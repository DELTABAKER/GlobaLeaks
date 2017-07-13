#        -*- encoding: utf-8 -*-
# Implements configuration of Tor hidden service

import os
from datetime import timedelta

from globaleaks import models
from globaleaks.handlers.admin.node import db_admin_serialize_node
from globaleaks.handlers.admin.notification import db_get_notification
from globaleaks.handlers.admin.user import db_get_admin_users
from globaleaks.handlers.user import user_serialize_user
from globaleaks.jobs.base import ServiceJob
from globaleaks.orm import transact
from globaleaks.settings import GLSettings
from globaleaks.utils.templating import Templating
from globaleaks.utils.utility import datetime_now, datetime_null

import txtorcon
from txtorcon import build_local_tor_connection
from twisted.internet import reactor
from twisted.internet.error import ConnectionRefusedError
from twisted.internet.defer import inlineCallbacks, Deferred

from globaleaks.models.config import NodeFactory, PrivateFactory
from globaleaks.rest.apicache import GLApiCache
from globaleaks.utils.utility import deferred_sleep, log

try:
   from txtorcon.torconfig import EphemeralHiddenService
except ImportError:
   from globaleaks.mocks.txtorcon_mocks import EphemeralHiddenService


__all__ = ['OnionService']


@transact
def get_onion_service_info(store):
    node_fact = NodeFactory(store)
    hostname = node_fact.get_val('onionservice')

    priv_fact = PrivateFactory(store)
    key = priv_fact.get_val('tor_onion_key')

    return hostname, key


@transact
def set_onion_service_info(store, hostname, key):
    node_fact = NodeFactory(store)
    node_fact.set_val('onionservice', hostname)

    priv_fact = PrivateFactory(store)
    priv_fact.set_val('tor_onion_key', key)


class OnionService(ServiceJob):
    name = "OnionService"
    threaded = False
    print_startup_error = True

    @inlineCallbacks
    def service(self, restart_deferred):
        hostname, key = yield get_onion_service_info()

        control_socket = '/var/run/tor/control'

        def startup_callback(tor_conn):
            self.print_startup_error = True
            tor_conn.protocol.on_disconnect = restart_deferred

            log.debug('Successfully connected to Tor control port')

            hs_loc = ('80 localhost:8083')
            if hostname == '' and key == '':
                log.info('Creating new onion service')
                ephs = EphemeralHiddenService(hs_loc)
            else:
                log.info('Setting up existing onion service %s', hostname)
                ephs = EphemeralHiddenService(hs_loc, key)

            @inlineCallbacks
            def initialization_callback(ret):
                log.info('Initialization of hidden-service %s completed.', ephs.hostname)
                if hostname == '' and key == '':
                    yield set_onion_service_info(ephs.hostname, ephs.private_key)

            d = ephs.add_to_tor(tor_conn.protocol)
            d.addCallback(initialization_callback) # pylint: disable=no-member

        def startup_errback(err):
            if self.print_startup_error:
                # Print error only on first run or failure or on a failure subsequent to a success condition
                self.print_startup_error = False
<<<<<<< 340905d52f0c35a0c5241b2db69dbc12cb3dadf9
                log.err('Failed to initialize Tor connection; error: %s' % err)
=======
                log.err('Failed to initialize Tor connection; error: %s', err) # pylint: disable=too-many-arguments
>>>>>>> Silence pylint warning on log.err

            restart_deferred.callback(None)

        if not os.path.exists(control_socket):
            log.err('Tor control port not open on /var/run/tor/control; waiting for Tor to become available')
            while not os.path.exists(control_socket):
                yield deferred_sleep(1)

        if not os.access(control_socket, os.R_OK):
            log.err('Unable to access /var/run/tor/control; manual permission recheck needed')
            while not os.access(control_socket, os.R_OK):
                yield deferred_sleep(1)

        d = build_local_tor_connection(reactor)
        d.addCallback(startup_callback)
        d.addErrback(startup_errback)

    def operation(self):
        deferred = Deferred()

        self.service(deferred)

        return deferred
