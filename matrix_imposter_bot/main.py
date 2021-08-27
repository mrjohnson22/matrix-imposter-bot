import re
from traceback import format_exception

from flask import request
from sqlite3 import IntegrityError

from . import app
from . import config
from . import messages
from . import utils
from .apputils import mx_request, post_message, post_message_status, MxRoomLink, MxUserLink, is_room_id

CONTROL_ROOM_NAME = 'ImposterBot control room'

@app.teardown_appcontext
def teardown(exc):
    utils.close_db_conn()


def validate_hs_token(request_args):
    if 'access_token' not in request_args:
        return ({'errcode': 'M_UNAUTHORIZED'}, 401)
    if request_args['access_token'] != config.hs_token:
        return ({'errcode': 'M_FORBIDDEN'}, 403)
    return None


def get_committed_txn_event_idxs(txnId):
    print(f'\n!!!\nreceiving txnId = {txnId}')
    ret = []
    c = utils.get_db_conn().cursor()
    for row in c.execute('SELECT event_idx FROM transactions_in WHERE txnId=(?)', (txnId,)):
        ret.append(row[0])
    print(f'Events we saw already = {ret}')
    return ret

def commit_txn_event(txnId, event_idx):
    print(f'Successfully handled event #{event_idx} of txnId = {txnId}')
    conn = utils.get_db_conn()
    conn.execute('INSERT INTO transactions_in VALUES (?, ?)', (txnId, event_idx))
    # This will commit everything done during the event!
    conn.commit()


def get_listening_room_users(room_id, exclude_users=[]):
    bot_in_room = True
    r = mx_request('GET', f'/_matrix/client/r0/rooms/{room_id}/joined_members')
    if r.status_code == 403:
        # Fall back to other API which remembers users of room bot used to be in
        bot_in_room = False
        r = mx_request('GET', f'/_matrix/client/r0/rooms/{room_id}/members?membership=join')
    elif r.status_code != 200:
        return None

    # A listening user is a user with a control room.
    listening_users = set()
    c = utils.get_db_conn().cursor()
    for row in c.execute('SELECT mxid FROM control_rooms'):
        listening_users.add(row[0])

    users = set()
    if bot_in_room:
        for member in r.json()['joined']:
            users.add(member)
    else:
        for member_event in r.json()['chunk']:
            users.add(member_event['state_key'])

    return users.difference(exclude_users).intersection(listening_users)


def is_user_in_monitored_room(mxid, room_id):
    # TODO consider caching room memberships in the DB
    c = utils.get_db_conn().cursor()
    c.execute('SELECT 1 FROM rooms WHERE room_id=?', (room_id,))
    if not utils.fetchone_single(c):
        return False

    r = mx_request('GET', f'/_matrix/client/r0/rooms/{room_id}/joined_members')
    if r.status_code != 200:
        return False

    return mxid in r.json()['joined']

def get_rooms_for_user(mxid):
    # TODO consider caching room memberships in the DB
    room_list = []
    c = utils.get_db_conn().cursor()
    for row in c.execute('SELECT room_id FROM rooms'):
        room_id = row[0]
        r = mx_request('GET', f'/_matrix/client/r0/rooms/{room_id}/joined_members')
        if r.status_code == 200 and mxid in r.json()['joined']:
            room_list.append(room_id)
    return room_list

def get_placeholders_for_room_list(room_list):
    return f'{",".join(["?"]*len(room_list))}'


def is_user_blacklisted(target_user, mimic_user, room_id):
    c = utils.get_db_conn().cursor()
    c.execute('SELECT blacklist FROM blacklists WHERE mimic_user=? AND room_id=?', (mimic_user, room_id))
    row = c.fetchone()
    if row == None:
        c.execute('SELECT blacklist FROM blacklists WHERE mimic_user=? AND room_id is NULL', (mimic_user,))
        row = c.fetchone()
    blacklist = row[0] if row != None else None

    if blacklist != None:
        for blacklist_word in blacklist.split():
            if re.match(blacklist_word, target_user):
                return True

    return False


def insert_control_room(mxid, room_id):
    utils.get_db_conn().execute('INSERT INTO control_rooms VALUES (?, ?, NULL)', (mxid, room_id))

def find_or_prepare_control_room(mxid):
    control_room = find_existing_control_room(mxid)

    if control_room == None:
        is_new_room = True
        r = mx_request('POST',
                '/_matrix/client/r0/createRoom',
                json={
                    'name': CONTROL_ROOM_NAME,
                    'topic': 'Room for managing ImposterBot settings',
                    'invite': [mxid],
                    'creation_content': {'m.federate': False},
                    'preset': 'trusted_private_chat',
                    'is_direct': True
                })

        if r.status_code == 200:
            control_room = r.json()['room_id']
            insert_control_room(mxid, control_room)

    else:
        is_new_room = False

    return control_room, is_new_room

def find_existing_control_room(mxid):
    return utils.fetchone_single(
        utils.get_db_conn().execute('SELECT room_id FROM control_rooms WHERE mxid=?', (mxid,)))

def get_mimic_user(target_room):
    return utils.fetchone_single(
        utils.get_db_conn().execute('SELECT mimic_user FROM rooms WHERE room_id=?', (target_room,)))

def is_control_room(room_id):
    return utils.fetchone_single(
        utils.get_db_conn().execute('SELECT 1 FROM control_rooms WHERE room_id=?', (room_id,))) != None

def get_control_room_user(room_id):
    return utils.fetchone_single(
        utils.get_db_conn().execute('SELECT mxid FROM control_rooms WHERE room_id=?', (room_id,)))


def get_mimic_info_for_room_and_sender(room_id, sender):
    mimic_user = None
    access_token = None

    c = utils.get_db_conn().cursor()
    c.execute('SELECT mimic_user, access_token FROM rooms JOIN control_rooms ON rooms.mimic_user=control_rooms.mxid WHERE rooms.room_id=?', (room_id,))
    row = c.fetchone()
    if row != None:
        mimic_user, access_token = row
        if mimic_user == sender:
            # Never replay the mimic user's own messages
            mimic_user = None

        if mimic_user != None and access_token != None and is_user_blacklisted(sender, mimic_user, room_id):
            mimic_user = None

    return mimic_user, access_token


def control_room_notify(user_to, target_room_info, notify_fn, *args):
    control_room = find_existing_control_room(user_to)
    if control_room == None:
        return True

    if target_room_info.id != control_room:
        # TODO non-blocking
        return command_notify(control_room, target_room_info, True, notify_fn, *args)
    else:
        return True

def command_notify(control_room, target_room_info, set_latest, notify_fn, *args):
    # Use this when the control room is known & a reply link is needed
    r, reply_link = notify_fn(control_room, target_room_info, *args)
    if r != None and r.status_code == 200:
        if reply_link:
            event_id = r.json()['event_id']
            c = utils.get_db_conn().cursor()
            c.execute('INSERT INTO reply_links VALUES (?, ?, ?)',
                (control_room, event_id, target_room_info.id))
            if set_latest:
                c.execute('INSERT INTO latest_reply_link VALUES (?, ?)',
                    (control_room, event_id))
        return True
    else:
        return False

def notify_bot_joined(control_room, target_room_info):
    return post_message(control_room,
        *messages.bot_joined(target_room_info)), True

def notify_user_joined(control_room, target_room_info):
    mimic_user = get_mimic_user(target_room_info.id)
    return post_message(control_room,
        *messages.user_joined(target_room_info, MxUserLink(mimic_user))), True

def notify_bot_left(control_room, target_room_info):
    return post_message(control_room,
        *messages.bot_left(target_room_info)), False

def notify_accepted_mimic(control_room, target_room_info):
    return post_message(control_room,
        *messages.accepted_mimic(target_room_info)), True

def notify_mimic_taken(control_room, target_room_info, mimic_user_info):
    return post_message(control_room,
        *messages.mimic_taken(target_room_info, mimic_user_info)), True

def notify_mimic_user_left(control_room, target_room_info, mimic_user_info):
    return post_message(control_room,
        *messages.mimic_user_left(target_room_info, mimic_user_info)), True

def notify_room_name(control_room, target_room_info):
    return post_message(control_room,
        *messages.room_name(target_room_info)), True

def notify_room_name_and_mimic_user(control_room, target_room_info, mimic_user_info):
    return post_message(control_room,
        *messages.room_name_and_mimic_user(target_room_info, mimic_user_info)), True

def notify_expired_token(control_room, target_room_info):
    return post_message(control_room, messages.expired_token()), False


# TODO move all this to its own file once I think of a good way to remove circular deps
from inspect import signature

def run_command(command_text, sender, control_room, replied_event=None):
    command_word = command_text[0].lower()
    command = COMMANDS.get(command_word)
    if command == None:
        return post_message_status(control_room, messages.invalid_command())

    command_args = command_text[1:]
    is_room_command = len(signature(command.func).parameters) == 4

    if not is_room_command:
        return command.func(command_args, sender, control_room)
    else:
        target_room = None
        if len(command_args) >= 1 and is_room_id(command_args[0]):
            room_arg = command_args.pop(0)
            if room_arg[0] == '#':
                room_alias = room_arg.replace('#', '%23')
                r = mx_request('GET', f'/_matrix/client/r0/directory/room/{room_alias}')
                if r.status_code == 200:
                    target_room = r.json()['room_id']
            elif room_arg[0] == '!':
                target_room = room_arg
        elif command.uses_reply_link:
            c = utils.get_db_conn().cursor()
            if replied_event != None:
                c.execute('SELECT room_id FROM reply_links WHERE control_room=? AND event_id=?',
                    (control_room, replied_event))
            else:
                c.execute('SELECT room_id FROM reply_links NATURAL JOIN latest_reply_link WHERE control_room=?',
                    (control_room,))

            target_room = utils.fetchone_single(c)

        return command.func(
            command_args, sender, control_room,
            MxRoomLink(target_room) if target_room and is_user_in_monitored_room(sender, target_room) else None)


def cmd_help(command_args, sender, control_room):
    text = ''
    for command_word, command in COMMANDS.items():
        if command.help != None:
            example = f'{command.example} :' if command.example else ':'
            text += f'> {command_word} {example} {command.help}\n\n'

    return post_message_status(control_room, text)

def cmd_register_token(command_args, sender, control_room):
    # Validate token first
    if len(command_args) < 1:
        return post_message_status(control_room, messages.empty_token())

    access_token = command_args[0]
    r = mx_request('GET', '/_matrix/client/r0/account/whoami', access_token=access_token)
    if r.status_code == 200 and r.json()['user_id'] == sender:
        utils.get_db_conn().execute('UPDATE control_rooms SET access_token=? WHERE mxid=?', (access_token, sender))
        return post_message_status(control_room, messages.received_token())
    else:
        return post_message_status(control_room, messages.invalid_token())

def cmd_revoke_token(command_args, sender, control_room):
    unmimic_user(sender)
    c = utils.get_db_conn().execute('UPDATE control_rooms SET access_token=NULL WHERE mxid=?', (sender,))
    return post_message_status(control_room,
        messages.revoked_token() if c.rowcount == 1 else messages.no_revoke_token())

def cmd_set_mimic_user(command_args, sender, control_room, target_room_info):
    if target_room_info == None:
        return post_message_status(control_room, messages.no_room())

    c = utils.get_db_conn().cursor()
    c.execute('SELECT access_token FROM control_rooms WHERE mxid=?', (sender,))
    if utils.fetchone_single(c) == None:
        return post_message_status(control_room, messages.cant_mimic())
    else:
        mimic_user = get_mimic_user(target_room_info.id)
        if mimic_user == sender:
            return post_message_status(control_room, *messages.already_mimic(target_room_info))
        elif mimic_user != None:
            return post_message_status(control_room, *messages.rejected_mimic(target_room_info, MxUserLink(mimic_user)))
        else:
            c.execute('UPDATE rooms SET mimic_user=? WHERE room_id=?', (sender, target_room_info.id))
            event_success = command_notify(
                control_room, target_room_info, True,
                notify_accepted_mimic)

            # Notify other users that someone took mimic rights
            room_users = get_listening_room_users(target_room_info.id, [config.as_botname, sender])
            if room_users != None and len(room_users) > 0:
                sender_info = MxUserLink(sender)
                for room_member in room_users:
                    event_success = control_room_notify(
                        room_member, target_room_info,
                        notify_mimic_taken, sender_info) and event_success
            elif room_users == None:
                event_success = False

            return event_success

def cmd_unset_user(command_args, sender, control_room, target_room_info):
    if target_room_info == None:
        return post_message_status(control_room, messages.no_room())

    c = utils.get_db_conn().cursor()
    c.execute('UPDATE rooms SET mimic_user=NULL WHERE mimic_user=? AND room_id=?', (sender, target_room_info.id))
    if c.rowcount != 0:
        event_success = post_message_status(control_room, *messages.stopped_mimic(target_room_info))

        # Notify other users that they can be mimic targets
        room_users = get_listening_room_users(target_room_info.id, [config.as_botname, sender])
        if room_users != None and len(room_users) > 0:
            sender_info = MxUserLink(sender)
            for room_member in room_users:
                event_success = control_room_notify(
                    room_member, target_room_info,
                    notify_mimic_user_left, sender_info) and event_success
        elif room_users == None:
            event_success = False

        return event_success
    else:
        return post_message_status(control_room,
            *(messages.never_mimicked(target_room_info) if c.rowcount == 1 else messages.never_mimicked(target_room_info)))

def cmd_set_mode(command_args, sender, control_room, target_room_info):
    if len(command_args) < 1:
        return post_message_status(control_room, messages.invalid_mode())

    c = utils.get_db_conn().cursor()

    mode = command_args[0]
    if mode == 'default' and target_room_info != None:
        c.execute('DELETE FROM response_modes WHERE mimic_user=? AND room_id=?', (sender, target_room_info.id))
        mfunc = messages.default_response_mode_in_room if c.rowcount != 0 else messages.same_default_response_mode_in_room
        return post_message_status(control_room, *mfunc(target_room_info))
    elif mode == 'echo':
        replace = 0
    elif mode == 'replace':
        replace = 1
    else:
        return post_message_status(control_room, messages.invalid_mode())

    noop = False
    if target_room_info == None:
        if replace:
            try:
                c.execute('INSERT INTO response_modes VALUES (?,NULL,1)', (sender,))
            except IntegrityError:
                noop = True
        else:
            c.execute('DELETE FROM response_modes WHERE mimic_user=? AND room_id is NULL', (sender,))
            noop = c.rowcount == 0

        mfunc = messages.set_response_mode if not noop else messages.same_response_mode
        return post_message_status(control_room, mfunc(replace))

    else:
        c.execute('SELECT replace FROM response_modes WHERE mimic_user=? AND room_id=?', (sender, target_room_info.id))
        oldreplace = utils.fetchone_single(c)
        if oldreplace == replace:
            noop = True
        elif oldreplace == None:
            c.execute('INSERT INTO response_modes VALUES (?,?,?)', (sender, target_room_info.id, replace))
        else:
            c.execute('UPDATE response_modes SET replace=? WHERE mimic_user=? AND room_id=?', (replace, sender, target_room_info.id))

        mfunc = messages.set_response_mode_in_room if not noop else messages.same_response_mode_in_room
        return post_message_status(control_room, *mfunc(replace, target_room_info))

def cmd_set_blacklist(command_args, sender, control_room, target_room_info):
    if len(command_args) < 1:
        return post_message_status(control_room, messages.empty_blacklist())

    c = utils.get_db_conn().cursor()

    # TODO match user IDs for all but single-word special cases
    blacklist = ' '.join(command_args)
    if blacklist == 'default' and target_room_info != None:
        c.execute('DELETE FROM blacklists WHERE mimic_user=? AND room_id=?', (sender, target_room_info.id))
        mfunc = messages.default_blacklist_in_room if c.rowcount != 0 else messages.same_default_blacklist_in_room
        return post_message_status(control_room, *mfunc(target_room_info))
    elif blacklist == 'none':
        blacklist = None

    # TODO consider noop messages, but probably unnecessary
    if target_room_info == None and blacklist == None:
        c.execute('DELETE FROM blacklists WHERE mimic_user=? AND room_id is NULL', (sender,))
    else:
        c.execute('INSERT INTO blacklists VALUES (?,?,?)', (sender, target_room_info.id if target_room_info != None else None, blacklist))

    if target_room_info == None:
        return post_message_status(control_room, messages.set_blacklist())
    else:
        return post_message_status(control_room, *messages.set_blacklist_in_room(target_room_info))

def cmd_get_blacklist(command_args, sender, control_room, target_room_info):
    query = 'SELECT blacklist FROM blacklists WHERE mimic_user=? AND room_id IS ?'
    c = utils.get_db_conn().cursor()
    c.execute(query, (sender, target_room_info.id if target_room_info else None))
    row = c.fetchone()
    if target_room_info != None and row == None:
        c.execute(query, (sender, None))
        default_blacklist = utils.fetchone_single(c)
        if default_blacklist == None:
            default_blacklist = 'no blacklist'
        return post_message_status(control_room, messages.blacklist_follows_default(default_blacklist))
    else:
        blacklist = row[0] if row != None else None
        return post_message_status(control_room, blacklist if blacklist else messages.no_blacklist())

def cmd_show_status(command_args, sender, control_room):
    # TODO allow requesting room-specific status
    c = utils.get_db_conn().cursor()
    # Don't quick-reply to anything
    c.execute('DELETE FROM latest_reply_link WHERE control_room=?', (control_room,))

    mimic_room_infos = []
    for row in c.execute('SELECT room_id FROM rooms WHERE mimic_user=?', (sender,)):
        room_id = row[0]
        mimic_room_infos.append(MxRoomLink(room_id))

    sender_rooms = get_rooms_for_user(sender)
    placeholders = get_placeholders_for_room_list(sender_rooms)

    # TODO distinguish between echo and replace
    monitored_room_infos = []
    for row in c.execute(f'SELECT room_id, mimic_user FROM rooms WHERE room_id IN ({placeholders}) ' \
            f'AND mimic_user IS NOT NULL ' \
            f'AND mimic_user IS NOT ?', (*sender_rooms, sender)):
        room_id, mimic_user = row
        if not is_user_blacklisted(sender, mimic_user, room_id):
            monitored_room_infos.append((MxRoomLink(room_id), MxUserLink(mimic_user)))

    if len(mimic_room_infos) == 0:
        if not post_message_status(control_room, messages.mimic_none()):
            return False
    else:
        if not post_message_status(control_room, messages.mimic_status()):
            return False
        for target_room_info in mimic_room_infos:
            if not command_notify(control_room, target_room_info, False, notify_room_name):
                return False

    if len(monitored_room_infos) == 0:
        if not post_message_status(control_room, messages.monitor_none()):
            return False
    else:
        if not post_message_status(control_room, messages.monitor_status()):
            return False
        for target_room_info, user_info in monitored_room_infos:
            if not command_notify(control_room, target_room_info, False, notify_room_name_and_mimic_user, user_info):
                return False

    return True

def cmd_show_actions(command_args, sender, control_room):
    c = utils.get_db_conn().cursor()
    # Don't quick-reply to anything after this
    c.execute('DELETE FROM latest_reply_link WHERE control_room=?', (control_room,))

    sender_rooms = get_rooms_for_user(sender)
    placeholders = get_placeholders_for_room_list(sender_rooms)

    mimic_room_infos = []
    for row in c.execute(f'SELECT room_id FROM rooms WHERE room_id IN ({placeholders}) AND mimic_user IS NULL', sender_rooms):
        room_id = row[0]
        mimic_room_infos.append(MxRoomLink(room_id))

    if len(mimic_room_infos) == 0:
        if not post_message_status(control_room, messages.mimic_none_available()):
            return False
    else:
        if not post_message_status(control_room, messages.mimic_available()):
            return False
        for target_room_info in mimic_room_infos:
            if not command_notify(control_room, target_room_info, False, notify_room_name):
                return False

    return True

class Command:
    # TODO template and description
    def __init__(self, func, example, help, uses_reply_link=False):
        self.func = func
        self.example = example
        self.help = help
        self.uses_reply_link = uses_reply_link

COMMANDS = {
    'help':         Command(cmd_help, None, None),
    'token':        Command(cmd_register_token, '<access-token>', messages.cmd_token),
    'revoke':       Command(cmd_revoke_token, None, messages.cmd_revoke),
    'mimicme':      Command(cmd_set_mimic_user, '[room_alias_or_id]', messages.cmd_mimicme, True),
    'stopit':       Command(cmd_unset_user, '[room_alias_or_id]', messages.cmd_stopit, True),
    'setmode':      Command(cmd_set_mode, '[room_alias_or_id] echo|replace|default', messages.cmd_setmode),
    'blacklist':    Command(cmd_set_blacklist, '[room_alias_or_id] <user-id-patterns>', messages.cmd_blacklist),
    'getblacklist': Command(cmd_get_blacklist, '[room_alias_or_id]', messages.cmd_getblacklist),
    'status':       Command(cmd_show_status, None, messages.cmd_status),
    'actions':      Command(cmd_show_actions, None, messages.cmd_actions)
}


def bot_leave_room(room_id):
    r = mx_request('POST', f'/_matrix/client/r0/rooms/{room_id}/leave')
    # If 403, bot was somehow removed from the room without it knowing.
    # Don't hard-fail on that, otherwise we'll never recover!!
    return r.status_code == 200 or r.status_code == 403

def user_leave_room(member, room_left):
    event_success = True
    c = utils.get_db_conn().cursor()
    c.execute('UPDATE rooms SET mimic_user=NULL WHERE mimic_user=? AND room_id=?', (member, room_left))
    if c.rowcount != 0:
        # User was mimic target: remove all room-specific rules for the room
        c.execute('DELETE FROM response_modes WHERE mimic_user=? AND room_id=?', (member, room_left))
        c.execute('DELETE FROM blacklists WHERE mimic_user=? AND room_id=?', (member, room_left))

        room_users = get_listening_room_users(room_left, [config.as_botname, member])
        if room_users != None:
            room_left_info = MxRoomLink(room_left)
            member_info = MxUserLink(member)
            for room_member in room_users:
                # TODO non-blocking? Success gating or not? Do the same for other occurrences of this pattern.
                event_success = control_room_notify(
                    room_member, room_left_info,
                    notify_mimic_user_left, member_info) and event_success
        else:
            event_success = False

    return event_success

def unmimic_user(mxid):
    # TODO have a "multi" version of the leave notification...
    event_success = True
    c = utils.get_db_conn().cursor()
    for row in c.execute('SELECT room_id FROM rooms WHERE mimic_user=?', (mxid,)):
        event_success = user_leave_room(mxid, row[0]) and event_success

    return event_success


def prepend_with_author(message, sender_info, isHTML):
    if not isHTML:
        author = sender_info.text
        linebreak = '\n'
    else:
        author = sender_info.link
        linebreak = '<br>'

    return '{0} says:{2}{1}'.format(author, message, linebreak*2)


@app.route('/transactions/<int:txnId>', methods=['PUT'])
def transactions(txnId):
    response = validate_hs_token(request.args)
    if response is not None:
        return response

    # Assume success until failure
    txn_success = True

    committed_event_idxs = get_committed_txn_event_idxs(txnId)
    events = request.get_json()['events']
    seen_event_ids = {}
    for i in range(len(events)):

        if len(committed_event_idxs) > 0 and i == committed_event_idxs[0]:
            committed_event_idxs.pop(0)
            continue

        # Assume success until failure
        event_success = True

        event = events[i]
        event_id = event['event_id']
        seen_event_id = event_id
        room_id = event.get('room_id')
        content = event['content']
        type = event['type']

        print('\n---BEGIN EVENT')
        print('type: ' + type)
        for key in event:
            if key != 'type':
                print(f'{key}: {event[key]}')
        print('--- END  EVENT')

        if type.find('m.room') == 0:
            stype = type[7:]
            sender = event['sender']

            c = utils.get_db_conn().cursor()

            if stype == 'member':
                member = event['state_key']
                membership = content['membership']

                # TODO map of memberships to functions

                if membership == 'invite':
                    if member == config.as_botname:
                        refused = False
                        if content.get('is_direct'):
                            # Only accept 1:1 invites if bot doesn't already have a control room for the inviter.
                            # TODO Does this need to handle invites to existing "direct" rooms with >1 people in them already...?
                            control_room = find_existing_control_room(sender)

                            if control_room != None:
                                refused = True
                                # Don't try to get the room name, because bot may not have access to it!
                                if post_message_status(control_room, messages.already_controlled()):
                                    event_success = bot_leave_room(room_id)
                            else:
                                insert_control_room(sender, room_id)

                        else:
                            # Always accept group chat invites.
                            # Since the bot was interacted with, create a control room for the sender.
                            c.execute('INSERT INTO rooms VALUES (?, NULL)', (room_id,))
                            event_success = find_or_prepare_control_room(sender) != None

                        if event_success and not refused:
                            # TODO non-blocking?
                            r = mx_request('POST', f'/_matrix/client/r0/rooms/{room_id}/join')
                            if r.status_code != 200:
                                event_success = False

                elif membership == 'join':
                    if utils.get_from_dict(event, 'prev_content', 'membership') == 'join':
                        # Do nothing if this is a repeat of a previous join event
                        # If not in a control room, post message for a user changing their name
                        if not is_control_room(room_id):
                            mimic_user, access_token = get_mimic_info_for_room_and_sender(room_id, sender)
                            if mimic_user != None and access_token != None:
                                old_sender_name = utils.get_from_dict(event, 'prev_content', 'displayname')
                                new_sender_name = utils.get_from_dict(event, 'content', 'displayname')
                                # TODO Riot Web always renders pills with their current name, not with the text you give it...
                                #old_sender_info = MxUserLink(sender, old_sender_name)
                                new_sender_info = MxUserLink(sender, new_sender_name)
                                event_success = post_message_status(
                                    room_id,
                                    *messages.user_renamed_msg(old_sender_name, new_sender_info),
                                    access_token)

                    else:
                        in_control_room = is_control_room(room_id)
                        if in_control_room == None:
                            # Only possibility is that the bot somehow joined a room it didn't know about.
                            # Just leave.
                            event_success = bot_leave_room(room_id)

                        elif in_control_room:
                            if member == config.as_botname:
                                # TODO non-blocking

                                control_room_user = get_control_room_user(room_id)
                                r = mx_request('GET', f'/_matrix/client/r0/rooms/{room_id}/joined_members')
                                bot_created_room = r.json()['joined'] == [config.as_botname]
                                if not bot_created_room:
                                    mx_request('PUT',
                                            f'/_matrix/client/r0/rooms/{room_id}/state/m.room.name',
                                            json={'name': CONTROL_ROOM_NAME})

                                # TODO Maybe don't send messages into this room until the user joins.
                                #      For now just don't auto-run "actions" because joins will be shown
                                event_success = \
                                        post_message_status(room_id, messages.welcome())
                                        #post_message_status(room_id, messages.welcome()) and \
                                        #cmd_show_actions(None, get_control_room_user(room_id), room_id)
                            else:
                                # If someone other than the control room's user joined it,
                                # send them a violation message.
                                # Do nothing otherwise (don't need to respond to a user joining their control room).
                                control_room_user = get_control_room_user(room_id)
                                if member != control_room_user:
                                    event_success = post_message_status(room_id,
                                        *messages.invalid_control_room_user(MxUserLink(member), MxUserLink(control_room_user)))

                        else:
                            if member == config.as_botname:
                                # Notify each present listening user that the bot joined this room.
                                room_users = get_listening_room_users(room_id, [config.as_botname])
                                if room_users != None:
                                    room_info = MxRoomLink(room_id)
                                    for room_member in room_users:
                                        event_success = control_room_notify(
                                            room_member, room_info,
                                            notify_bot_joined) and event_success
                                else:
                                    event_success = False

                            else:
                                mimic_user, access_token = get_mimic_info_for_room_and_sender(room_id, sender)
                                if mimic_user != None and access_token != None:
                                    sender_info = MxUserLink(sender)
                                    event_success = post_message_status(room_id, *messages.user_joined_msg(sender_info), access_token)

                                # Notify the user that they joined a room that the bot is in.
                                event_success = control_room_notify(
                                    member, MxRoomLink(room_id),
                                    notify_user_joined) and event_success

                elif membership == 'leave':
                    in_control_room = is_control_room(room_id)
                    control_room_user = get_control_room_user(room_id) if in_control_room else None
                    if in_control_room == None:
                        # Someone left an unmonitored room.
                        # Ignore.
                        pass

                    elif member == config.as_botname:
                        if in_control_room:
                            # Bot left a control room, so it should be shut down.
                            # Act as if the monitored user left all rooms they were being mimicked in.
                            event_success = unmimic_user(control_room_user)
                        else:
                            # For each listening user in room, say that bot left
                            room_users = get_listening_room_users(room_id, [config.as_botname])
                            if room_users != None:
                                room_info = MxRoomLink(room_id)
                                for room_member in room_users:
                                    event_success = control_room_notify(
                                        room_member, room_info,
                                        notify_bot_left) and event_success
                            else:
                                event_success = False

                        # NOTE This should trigger a lot of cascaded deletions!
                        c.execute(f'DELETE FROM {"rooms" if not in_control_room else "control_rooms"} WHERE room_id=?', (room_id,))

                    else:
                        if in_control_room:
                            if member == control_room_user:
                                # User left their control room or rejected an invite.
                                # Bot should leave the room too. Its leave event will handle the rest.
                                event_success = bot_leave_room(room_id) and event_success
                        else:
                            event_success = user_leave_room(member, room_id)

                            # If no one else is in the room, the bot should leave.
                            room_empty = False
                            r = mx_request('GET', f'/_matrix/client/r0/rooms/{room_id}/joined_members')
                            if r.status_code == 403:
                                room_empty = True
                            elif r.status_code == 200:
                                # Look for just 1 user, which is the bot itself
                                room_empty = len(r.json()['joined']) == 1
                            else:
                                event_success = False

                            if event_success:
                                if not room_empty:
                                    # If the room is not empty, relay a message saying the user left.
                                    mimic_user, access_token = get_mimic_info_for_room_and_sender(room_id, sender)
                                    if mimic_user != None and access_token != None:
                                        sender_info = MxUserLink(sender)
                                        post_message(room_id, *messages.user_left_msg(sender_info), access_token)
                                else:
                                    event_success = bot_leave_room(room_id)



            elif stype == 'message':
                if 'body' not in content:
                    # Event is redacted, ignore
                    pass
                elif is_control_room(room_id):
                    if sender == get_control_room_user(room_id):
                        replied_event = None
                        try:
                            replied_event = content['m.relates_to']['m.in_reply_to']['event_id']
                            body = content['formatted_body']
                            reply_end = body.find('</mx-reply>')
                            body = body[reply_end+11:]
                        except KeyError:
                            body = content['body']

                        event_success = run_command(body.split(), sender, room_id, replied_event)

                elif sender != config.as_botname:

                    # Create control room for a user who mentions the bot.
                    if content['body'].find(config.as_botname) != -1 or \
                            ('formatted_body' in content and content['formatted_body'].find(config.as_botname) != -1):
                        control_room, is_new_room = find_or_prepare_control_room(sender)
                        if control_room == None:
                            event_success = False
                        elif not is_new_room:
                            post_message(control_room, messages.ping())

                    else:
                        mimic_user = None
                        access_token = None

                        c.execute('SELECT 1 FROM generated_messages WHERE event_id=? AND room_id=?', (event_id, room_id))
                        if c.fetchone() == None:
                            mimic_user, access_token = get_mimic_info_for_room_and_sender(room_id, sender)

                        if mimic_user != None and access_token != None:
                            sender_info = MxUserLink(sender)

                            content['formatted_body'] = prepend_with_author(
                                content['formatted_body' if 'formatted_body' in content else 'body'], sender_info, True)

                            content['body'] = prepend_with_author(
                                content['body'], sender_info, False)

                            content['format'] = 'org.matrix.custom.html'

                            r = mx_request('PUT',
                                    f'/_matrix/client/r0/rooms/{room_id}/send/m.room.message/txnId',
                                    json=content,
                                    access_token=access_token)

                            if r.status_code == 200:
                                seen_event_id = r.json()['event_id']
                                c.execute('INSERT INTO generated_messages VALUES (?, ?)', (seen_event_id, room_id))

                                c.execute('SELECT replace FROM response_modes WHERE mimic_user=? AND room_id=?', (mimic_user, room_id))
                                replace = utils.fetchone_single(c)
                                if replace == None:
                                    c.execute('SELECT replace FROM response_modes WHERE mimic_user=? AND room_id is NULL', (mimic_user,))
                                    replace = utils.fetchone_single(c)

                                if replace:
                                    r = mx_request('PUT',
                                        f'/_matrix/client/r0/rooms/{room_id}/redact/{event_id}/txnId',
                                        json={'reason':'Replaced by ImposterBot'})
                                    if r.status_code not in [200, 403, 404]:
                                        event_success = False
                                    elif r.status_code == 200:
                                        seen_event_id = r.json()['event_id']

                            elif r.json()['errcode'] == 'M_UNKNOWN_TOKEN':
                                event_success = control_room_notify(
                                    mimic_user, MxRoomLink(room_id),
                                    notify_expired_token)
                            else:
                                # Unknown token is a "valid" error. For anything else, want to retry
                                event_success = False

            else:
                print(f'Unsupported room event type: {type}')
        else:
            print(f'Unsupported event type: {type}')

        if event_success:
            if room_id != None and not is_control_room(room_id):
                seen_event_ids[room_id] = seen_event_id
            commit_txn_event(txnId, i)
        else:
            print('\nEvent unsuccessful!!!!!')
            txn_success = False
            # Discard any uncommitted changes
            utils.close_db_conn()

    for room_id, event_id in seen_event_ids.items():
        # TODO non-blocking
        mx_request('POST', f'/_matrix/client/r0/rooms/{room_id}/receipt/m.read/{event_id}')

    return ({}, 200 if txn_success else 500)
