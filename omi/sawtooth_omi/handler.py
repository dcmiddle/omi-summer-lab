# Copyright 2017 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# -----------------------------------------------------------------------------

import hashlib

from google.protobuf.message import DecodeError

from sawtooth_sdk.processor.state import StateEntry
from sawtooth_sdk.processor.exceptions import InvalidTransaction
from sawtooth_sdk.processor.exceptions import InternalError
from sawtooth_sdk.protobuf.transaction_pb2 import TransactionHeader

from sawtooth_omi.protobuf.work_pb2 import Work
from sawtooth_omi.protobuf.recording_pb2 import Recording
from sawtooth_omi.protobuf.identity_pb2 import \
        IndividualIdentity
from sawtooth_omi.protobuf.identity_pb2 import \
        OrganizationalIdentity
from sawtooth_omi.protobuf.txn_payload_pb2 import OMITransactionPayload


# actions

# Right now the actions are doubling as a kind of type tag.
# This isn't very elegant, and something more suitable
# can be put in place when we know more about other kinds
# of actions that might be included.
WORK = 'SetWork'
RECORDING = 'SetRecording'
INDIVIDUAL = 'SetIndividualIdentity'
ORGANIZATION = 'SetOrganizationalIdentity'


# address
def _hash_name(name):
    return hashlib.sha512(name.encode('utf-8')).hexdigest()


FAMILY_NAME = 'OMI'
OMI_ADDRESS_PREFIX = _hash_name(FAMILY_NAME)[:6]


def _get_address_infix(action):
    infixes = {
        WORK: 'a0',
        RECORDING: 'a1',
        INDIVIDUAL: '00',
        ORGANIZATION: '01',
    }

    return infixes[action]


def _get_unique_key(obj, action):
    if action in (WORK, RECORDING):
        key = obj.title
    elif action in (INDIVIDUAL, ORGANIZATION):
        key = obj.name

    return key


def make_omi_address(obj, action):
    infix = _get_address_infix(action)
    key = _get_unique_key(obj, action)

    return OMI_ADDRESS_PREFIX + infix + _hash_name(key)[-62:]


class OMITransactionHandler:
    @property
    def family_name(self):
        return FAMILY_NAME

    @property
    def family_versions(self):
        return ['1.0']

    @property
    def encodings(self):
        return ['application/protobuf']

    @property
    def namespaces(self):
        return [OMI_ADDRESS_PREFIX]

    def apply(self, transaction, state):
        action, txn_obj, signer = _unpack_transaction(transaction)

        address = make_omi_address(txn_obj, action)

        state_obj = _get_state_object(state, address, action)

        # Check if the submitter is authorized to make changes,
        # then validate the transaction
        _check_authorization(state_obj, action, signer)
        _check_split_sums(txn_obj, action)
        _check_references(txn_obj, action)

        _set_state_object(state, address, txn_obj)


# objects

def _parse_object(obj_string, action):
    obj_types = {
        WORK: Work,
        RECORDING: Recording,
        INDIVIDUAL: IndividualIdentity,
        ORGANIZATION: OrganizationalIdentity,
    }

    obj_type = obj_types[action]

    try:
        parsed_obj = obj_type()
        parsed_obj.ParseFromString(obj_string)
        return parsed_obj
    except DecodeError:
        raise InvalidTransaction('Invalid action')


# transaction

def _unpack_transaction(transaction):
    '''
    return action, obj, signer
    '''
    header = TransactionHeader()
    header.ParseFromString(transaction.header)
    signer = header.signer_pubkey

    payload = OMITransactionPayload()
    payload.ParseFromString(transaction.payload)

    action = payload.action
    txn_obj = transaction.data

    obj = _parse_object(txn_obj, action)

    return action, obj, signer


def _check_authorization(state_obj, action, signer):
    if not state_obj:
        return

    if action in (WORK, RECORDING):
        pubkey = state_obj.pubkey
    elif action in (INDIVIDUAL, ORGANIZATION):
        pubkey = state_obj.registering_pubkey

    if pubkey != signer:
        raise InvalidTransaction('Signing key mismatch')


def _check_split_sums(obj, action):
    '''
    Raise InvalidTransaction if there are nonempty splits
    that don't add up to 100
    '''


def _check_references(obj, action):
    '''
    Raise InvalidTransaction if the object references anything
    that isn't in state, eg if a Work refers to a songwriter
    (IndividualIdentity) or a publisher (OrganizationalIdentity)
    that hasn't been registered
    '''


# state

def _get_state_object(state, address, action):
    try:
        state_entries = state.get([address])
        state_obj = state_entries[0].data
        obj = _parse_object(state_obj, action)
    except IndexError:
        obj = None

    return obj


def _set_state_object(state, address, obj):
    obj_string = obj.SerializeToString()

    addresses = state.set([
        StateEntry(
            address=address,
            data=obj_string)
    ])

    if not addresses:
        raise InternalError('State error')
