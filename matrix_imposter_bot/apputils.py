from . import config
from . import utils


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


def mx_request(method, endpoint, json=None, access_token=None, **kwargs):
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

    r = utils.make_request(method, config.hs_address + endpoint, json, headers, **kwargs)

    # TODO handle failure
    if txnId != None and r.status_code == 200:
        commit_txnId(txnId)

    return r


def get_room_name(room_id):
    r = mx_request('GET', f'/_matrix/client/r0/rooms/{room_id}/state/m.room.name')
    if r.status_code == 200:
        return r.json()['name']
    elif r.status_code == 404:
        r = mx_request('GET', f'/_matrix/client/r0/rooms/{room_id}/state/m.room.canonical_alias')
        if r.status_code == 200:
            return r.json()['alias']
        elif r.status_code == 404:
            return 'Unnamed room'

    return None


def post_message(room_id, message_plain, message_html=None):
    json={'body': message_plain, 'msgtype': 'm.text'}
    if message_html != None:
        json['format'] = 'org.matrix.custom.html'
        json['formatted_body'] = message_html

    return mx_request('PUT', f'/_matrix/client/r0/rooms/{room_id}/send/m.room.message/txnId', json)

def post_message_status(*args, **kwargs):
    return post_message(*args, **kwargs).status_code == 200
