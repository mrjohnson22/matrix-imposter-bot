from . import config
from . import utils

import re


class Linkable:
    def __init__(self, link, text):
        self._link = link
        self._text = text

    @property
    def link(self):
        return self._link

    @property
    def text(self):
        return self._text

class MxLinkable(Linkable):
    def __init__(self, id):
        super().__init__(None, None)
        self.id = id # invoke setter

    @property
    def id(self):
        return self._id

    @id.setter
    def id(self, id):
        self._id = id
        self._dirty = True

    @property
    def text(self):
        if self._dirty:
            self._update()
        return self._text if self._text else self._id

    @property
    def link(self):
        if self._dirty:
            self._update()
        return self._link

    def _update(self):
        self._text = self._updater()
        self._link = get_mx_link(self._id, self._text)
        #TODO if this is ever long-lived, there needs to be a way to re-dirty it
        self._dirty = self._text != None

    def _updater(self):
        raise NotImplementedError()

class MxRoomLink(MxLinkable):
    def _updater(self):
        return get_room_name(self._id)

class MxUserLink(MxLinkable):
    def _updater(self):
        return get_display_name(self._id)

def get_mx_link(id, text):
    return f'<a href="https://matrix.to/#/{id}">{text if text else id}</a>'

def get_link_fmt_pair(template, linkables, *args):
    texts = []
    links = []
    for linkable in linkables:
        texts.append(linkable.text)
        links.append(linkable.link)

    plain = template.format(*texts, *args)
    html = template.replace('\n', '<br>').format(*links, *args)
    return (plain, html)


room_pattern = re.compile('[#!][^:]+:[a-z0-9._:]+')
def is_room_id(room_id):
    return bool(room_pattern.fullmatch(room_id))


def get_next_txnId():
    conn = utils.get_db_conn()
    c = conn.cursor()
    c.execute('INSERT INTO transactions_out VALUES (null, 0)')
    c.execute('SELECT txnId FROM transactions_out WHERE txnId=(SELECT MAX(txnId) FROM transactions_out)')

    txnId = c.fetchone()[0]
    return txnId

def commit_txnId(txnId):
    utils.get_db_conn().execute(
        'UPDATE transactions_out SET committed=1 WHERE txnId=?', (txnId,))
    # Not actually committing here, relying on HS to no-op re-requests


def mx_request(method, endpoint, json=None, access_token=None, verbose=True, **kwargs):
    headers = {
        'Content-Type':'application/json',
        'Authorization':'Bearer {}'.format(
            access_token if access_token else config.as_token)
        };

    txnId = None
    if method == 'PUT':
        slash_index = endpoint.rfind('/') + 1
        if endpoint[slash_index:] == 'txnId':
            txnId = get_next_txnId()
            endpoint = endpoint[:slash_index] + str(txnId)

    r = utils.make_request(method, config.hs_address + endpoint, json, headers, verbose, **kwargs)

    # TODO handle failure
    if txnId != None and r.status_code == 200:
        commit_txnId(txnId)

    return r


def get_room_name(room_id):
    # TODO cache this in the DB!!
    r = mx_request('GET', f'/_matrix/client/r0/rooms/{room_id}/state/m.room.name')
    if r.status_code == 200:
        return r.json()['name']
    elif r.status_code == 404:
        r = mx_request('GET', f'/_matrix/client/r0/rooms/{room_id}/state/m.room.canonical_alias')
        if r.status_code == 200:
            return r.json()['alias']
        elif r.status_code == 404:
            return 'Unnamed room'

    # TODO This is really an error condition, but making it fatal is annoying
    return 'Unknown room'

def get_display_name(mxid):
    # TODO cache this in the DB!!
    # TODO consider failing on network error. But not failing makes it much easier.
    r = mx_request('GET', f'/_matrix/client/r0/profile/{mxid}/displayname')
    return r.json()['displayname'] if r.status_code == 200 else None


def post_message(room_id, message_plain, message_html=None, access_token=None):
    json={'body': message_plain, 'msgtype': 'm.text'}
    if message_html != None:
        json['format'] = 'org.matrix.custom.html'
        json['formatted_body'] = message_html

    return mx_request('PUT',
            f'/_matrix/client/r0/rooms/{room_id}/send/m.room.message/txnId',
            json,
            access_token=access_token)

def post_message_status(*args, **kwargs):
    return post_message(*args, **kwargs).status_code == 200
