from traceback import format_exception

from flask import request
from sqlite3 import IntegrityError

from . import app
from . import config
from . import messages
from . import utils
from .apputils import mx_request, post_message, post_message_status, get_room_name


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


def insert_control_room(mxid, room_id):
    c = utils.get_db_conn().cursor()
    c.execute('INSERT INTO rooms VALUES (?, 1)', (room_id,))
    c.execute('INSERT INTO control_rooms VALUES (?, ?)', (mxid, room_id))

def find_or_prepare_control_room(mxid):
    control_room = find_existing_control_room(mxid)

    if control_room == None:
        is_new_room = True
        r = mx_request('POST',
                '/_matrix/client/r0/createRoom',
                json={
                    'name': 'ImposterBot control room',
                    'topic': 'Room for managing ImposterBot settings',
                    'invite': [mxid],
                    'creation_content': {'m.federate': False},
                    'preset': 'private_chat',
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
        utils.get_db_conn().cursor().execute('SELECT room_id FROM control_rooms WHERE mxid=?', (mxid,)))

def get_mimic_user(target_room):
    return utils.fetchone_single(
        utils.get_db_conn().execute('SELECT mxid FROM mimic_rules WHERE room_id=?', (target_room,)))

def get_in_control_room(room_id):
    return utils.fetchone_single(
        utils.get_db_conn().execute('SELECT is_control FROM rooms WHERE room_id=?', (room_id,)))

def get_control_room_user(room_id):
    # TODO Is this join faster than a straight lookup? Maybe redesign the tables...
    return utils.fetchone_single(
        utils.get_db_conn().execute('SELECT mxid FROM rooms NATURAL JOIN control_rooms WHERE rooms.is_control=1 AND room_id=?', (room_id,)))


def control_room_notify(user_to, target_room, notify_fn, *args):
    control_room = find_existing_control_room(user_to)
    if control_room == None:
        return True

    if target_room != control_room:
        # TODO non-blocking
        return command_notify(control_room, target_room, True, notify_fn, *args)
    else:
        return True

def command_notify(control_room, target_room, set_latest, notify_fn, *args):
    # Use this when the control room is known & a reply link is needed
    r, reply_link = notify_fn(control_room, target_room, *args)
    if r != None and r.status_code == 200:
        if reply_link:
            event_id = r.json()['event_id']
            c = utils.get_db_conn().cursor()
            c.execute('INSERT INTO reply_links VALUES (?, ?, ?)',
                (control_room, event_id, target_room))
            if set_latest:
                c.execute('INSERT INTO latest_reply_link VALUES (?, ?)',
                    (control_room, event_id))
        return True
    else:
        return False

def notify_bot_joined(control_room, target_room, room_name):
    # Pass room_name to this since it's called in a loop
    return post_message(control_room,
        *messages.bot_joined(target_room, room_name)), True

def notify_user_joined(control_room, target_room):
    room_name = get_room_name(target_room)
    if room_name == None:
        return None, False
    else:
        return post_message(control_room,
            *messages.user_joined(target_room, room_name, get_mimic_user(target_room))), True

def notify_bot_left(control_room, target_room, room_name):
    # Pass room_name to this since it's called in a loop
    return post_message(control_room,
        *messages.bot_left(target_room, room_name)), False

def notify_user_left(control_room, target_room):
    room_name = get_room_name(target_room)
    if room_name == None:
        return None, False
    else:
        return post_message(control_room,
            *messages.user_left(target_room, room_name)), False

def notify_accepted_mimic(control_room, target_room, room_name):
    return post_message(control_room,
        *messages.accepted_mimic(target_room, room_name)), True

def notify_mimic_taken(control_room, target_room, mxid, room_name):
    return post_message(control_room,
        *messages.mimic_taken(mxid, target_room, room_name)), True

def notify_mimic_user_left(control_room, target_room, mxid, room_name):
    return post_message(control_room,
        *messages.mimic_user_left(mxid, target_room, room_name)), True

def notify_accepted_echo(control_room, target_room, room_name):
    return post_message(control_room,
        *messages.accepted_echo(target_room, room_name)), True

def notify_accepted_replace(control_room, target_room, room_name):
    return post_message(control_room,
        *messages.accepted_replace(target_room, room_name)), True

def notify_room_name(control_room, target_room, room_name):
    return post_message(control_room,
        *messages.room(target_room, room_name)), True

def notify_expired_token(control_room, target_room):
    return post_message(control_room, messages.expired_token()), False


# TODO move all this to its own file once I think of a good way to remove circular deps
from inspect import signature

def run_command(command, sender, control_room, replied_event=None):
    command_word = command[0].lower()
    command_func = COMMANDS.get(command_word)
    if command_func == None:
        return post_message_status(control_room, messages.invalid_command())

    command_args = command[1:]
    is_room_command = len(signature(command_func).parameters) == 5

    if not is_room_command:
        return command_func(command_args, sender, control_room)
    else:
        target_room = None
        if len(command_args) >= 1:
            room_arg = command_args.pop(0)
            if room_arg[0] == '#':
                room_alias = room_arg.replace('#', '%23')
                r = mx_request('GET', f'/_matrix/client/r0/directory/room/{room_alias}')
                if r.status_code == 200:
                    target_room = r.json()['room_id']
            elif room_arg[0] == '!':
                target_room = room_arg
        else:
            c = utils.get_db_conn().cursor()
            if replied_event != None:
                c.execute('SELECT room_id FROM reply_links WHERE control_room=? AND event_id=?',
                    (control_room, replied_event))
            else:
                c.execute('SELECT room_id FROM reply_links NATURAL JOIN latest_reply_link WHERE control_room=?',
                    (control_room,))

            target_room = utils.fetchone_single(c)

        room_name = get_room_name(target_room) if target_room != None else None
        if room_name == None:
            return post_message_status(control_room, messages.no_room())
        else:
            return command_func(command_args, sender, control_room, target_room, room_name)


def cmd_register_token(command_args, sender, control_room):
    # Validate token first
    access_token = command_args[0]
    r = mx_request('GET', '/_matrix/client/r0/account/whoami', access_token=access_token)
    if r.status_code == 200 and r.json()['user_id'] == sender:
        c = utils.get_db_conn().cursor()
        try:
            c.execute('INSERT INTO user_access_tokens VALUES (?, ?)',
                (sender, access_token))
        except IntegrityError:
            c.execute('UPDATE user_access_tokens SET access_token=? WHERE mxid=?',
                (access_token, sender))
        return post_message_status(control_room, messages.received_token())
    else:
        return post_message_status(control_room, messages.invalid_token())

def cmd_revoke_token(command_args, sender, control_room):
    unmimic_user(sender)
    c = utils.get_db_conn().execute('DELETE FROM user_access_tokens WHERE mxid=?', (sender,))
    return post_message_status(control_room,
        messages.revoked_token() if c.rowcount == 1 else messages.no_revoke_token())

def cmd_set_mimic_user(command_args, sender, control_room, target_room, room_name):
    c = utils.get_db_conn().cursor()
    if utils.fetchone_single(c.execute('SELECT access_token FROM user_access_tokens WHERE mxid=?', (sender,))) == None:
        return post_message_status(control_room, messages.cant_mimic())
    else:
        mimic_user = get_mimic_user(target_room)
        if mimic_user == sender:
            return post_message_status(control_room, *messages.already_mimic(target_room, room_name))
        elif mimic_user != None:
            return post_message_status(control_room, *messages.rejected_mimic(mimic_user, target_room, room_name))
        else:
            c.execute('INSERT INTO mimic_rules VALUES (?, ?)', (sender, target_room))
            event_success = command_notify(
                control_room, target_room, True,
                notify_accepted_mimic, room_name)

            # Notify other users that they can be victims
            room_users = get_listening_room_users(target_room, [config.as_botname, sender])
            if room_users != None:
                for room_member in room_users:
                    event_success = control_room_notify(
                        room_member, target_room,
                        notify_mimic_taken, sender, room_name) and event_success
            else:
                event_success = False

            return event_success

def cmd_set_echo_user(command_args, sender, control_room, target_room, room_name):
    return set_victim_user(sender, control_room, target_room, room_name, False)

def cmd_set_replace_user(command_args, sender, control_room, target_room, room_name):
    return set_victim_user(sender, control_room, target_room, room_name, True)

def set_victim_user(sender, control_room, target_room, room_name, replace):
    mimic_user = get_mimic_user(target_room)
    if mimic_user == None:
        return post_message_status(control_room, *messages.cannot_victimize(target_room, room_name))
    elif mimic_user == sender:
        return post_message_status(control_room, *messages.cannot_victimize_yourself(target_room, room_name))
    else:
        utils.get_db_conn().execute('INSERT INTO victim_rules VALUES (?, ?, ?)', (sender, target_room, replace))
        return command_notify(
            control_room, target_room, True,
            notify_accepted_echo if not replace else notify_accepted_replace, room_name)

def cmd_unset_user(command_args, sender, control_room, target_room, room_name):
    c = utils.get_db_conn().cursor()
    c.execute('DELETE FROM mimic_rules WHERE mxid=? AND room_id=?', (sender, target_room))
    if c.rowcount == 0:
        # Wasn't mimicking, were they a victim?
        c.execute('DELETE FROM victim_rules WHERE victim_id=? AND room_id=?', (sender, target_room))
        return post_message_status(control_room,
            *(messages.stopped_victim(target_room, room_name) if c.rowcount == 1 else messages.missed_listen(target_room, room_name)))
    else:
        event_success = post_message_status(control_room, *messages.stopped_mimic(target_room, room_name))

        # Notify other users that they can be mimic targets
        room_users = get_listening_room_users(target_room, [config.as_botname, sender])
        if room_users != None:
            for room_member in room_users:
                event_success = control_room_notify(
                    room_member, target_room,
                    notify_mimic_user_left, sender, room_name) and event_success
        else:
            event_success = False

        return event_success

def cmd_show_status(command_args, sender, control_room):
    c = utils.get_db_conn().cursor()
    # Don't quick-reply to anything
    c.execute('DELETE FROM latest_reply_link WHERE control_room=?', (control_room,))

    mimic_room_infos = []
    for row in c.execute('SELECT room_id FROM mimic_rules WHERE mxid=?', (sender,)):
        room_id = row[0]
        room_name = get_room_name(room_id)
        if room_name == None:
            return False
        mimic_room_infos.append((room_id, room_name))

    echo_room_infos = []
    for row in c.execute('SELECT room_id FROM victim_rules WHERE victim_id=? AND replace=0', (sender,)):
        room_id = row[0]
        room_name = get_room_name(room_id)
        if room_name == None:
            return False
        echo_room_infos.append((room_id, room_name))

    replace_room_infos = []
    for row in c.execute('SELECT room_id FROM victim_rules WHERE victim_id=? AND replace=1', (sender,)):
        room_id = row[0]
        room_name = get_room_name(room_id)
        if room_name == None:
            return False
        replace_room_infos.append((room_id, room_name))

    if len(mimic_room_infos) == 0:
        if not post_message_status(control_room, messages.mimic_none()):
            return False
    else:
        if not post_message_status(control_room, messages.mimic_status()):
            return False
        for target_room, room_name in mimic_room_infos:
            if not command_notify(control_room, target_room, False, notify_room_name, room_name):
                return False

    if len(echo_room_infos) == 0:
        if not post_message_status(control_room, messages.echo_none()):
            return False
    else:
        if not post_message_status(control_room, messages.echo_status()):
            return False
        for target_room, room_name in echo_room_infos:
            if not command_notify(control_room, target_room, False, notify_room_name, room_name):
                return False

    if len(replace_room_infos) == 0:
        if not post_message_status(control_room, messages.replace_none()):
            return False
    else:
        if not post_message_status(control_room, messages.replace_status()):
            return False
        for target_room, room_name in replace_room_infos:
            if not command_notify(control_room, target_room, False, notify_room_name, room_name):
                return False

    return True

def cmd_show_actions(command_args, sender, control_room):
    c = utils.get_db_conn().cursor()
    # Don't quick-reply to anything
    c.execute('DELETE FROM latest_reply_link WHERE control_room=?', (control_room,))

    # TODO Bot could keep track of which users are in which rooms itself...
    sender_rooms = []
    for row in c.execute('SELECT room_id FROM rooms WHERE is_control=0'):
        room_id = row[0]
        r = mx_request('GET', f'/_matrix/client/r0/rooms/{room_id}/joined_members')
        if r.status_code == 200 and sender in r.json()['joined']:
            sender_rooms.append(room_id)

    placeholders = f'{",".join(["?"]*len(sender_rooms))}'

    mimic_room_infos = []
    for row in c.execute((
        'SELECT room_id FROM rooms WHERE is_control=0'
        f' AND room_id IN ({placeholders})'
         ' AND room_id NOT IN (SELECT room_id FROM mimic_rules)'),
            sender_rooms):
        room_id = row[0]
        room_name = get_room_name(room_id)
        if room_name == None:
            return False
        mimic_room_infos.append((room_id, room_name))

    victim_room_infos = []
    for row in c.execute((
        'SELECT room_id FROM rooms WHERE is_control=0'
        f' AND room_id IN ({placeholders})'
         ' AND room_id     IN (SELECT room_id FROM  mimic_rules WHERE mxid!=?)'
         ' AND room_id NOT IN (SELECT room_id FROM victim_rules WHERE victim_id=?)'),
            sender_rooms + [sender, sender]):
        room_id = row[0]
        room_name = get_room_name(room_id)
        if room_name == None:
            return False
        victim_room_infos.append((room_id, room_name))

    if len(mimic_room_infos) == 0:
        if not post_message_status(control_room, messages.mimic_none_available()):
            return False
    else:
        if not post_message_status(control_room, messages.mimic_available()):
            return False
        for target_room, room_name in mimic_room_infos:
            if not command_notify(control_room, target_room, False, notify_room_name, room_name):
                return False

    if len(victim_room_infos) == 0:
        if not post_message_status(control_room, messages.victim_none_available()):
            return False
    else:
        if not post_message_status(control_room, messages.victim_available()):
            return False
        for target_room, room_name in victim_room_infos:
            if not command_notify(control_room, target_room, False, notify_room_name, room_name):
                return False

    return True


COMMANDS = {
    'token':        cmd_register_token,
    'revoke':       cmd_revoke_token,
    'mimicme':      cmd_set_mimic_user,
    'echome':       cmd_set_echo_user,
    'replaceme':    cmd_set_replace_user,
    'stopit':       cmd_unset_user,
    'status':       cmd_show_status,
    'actions':      cmd_show_actions
}


def bot_leave_room(room_id):
    r = mx_request('POST', f'/_matrix/client/r0/rooms/{room_id}/leave')
    return r.status_code == 200

def user_leave_room(member, room_left):
    event_success = True
    c = utils.get_db_conn().cursor()
    c.execute('DELETE FROM mimic_rules WHERE mxid=? AND room_id=?', (member, room_left))
    if c.rowcount > 0:
        # User was mimic target: remove all rules for the room
        c.execute('DELETE FROM victim_rules WHERE room_id=?', (room_left,))
        room_users = get_listening_room_users(room_left, [config.as_botname, member])
        if room_users != None:
            room_name = get_room_name(room_left)
            if room_name == None:
                event_success = False
            else:
                for room_member in room_users:
                    # TODO non-blocking? Success gating or not? Do the same for other occurrences of this pattern.
                    event_success = control_room_notify(
                        room_member, room_left,
                        notify_mimic_user_left, member, room_name) and event_success
        else:
            event_success = False
    else:
        # User wasn't mimic target: just remove any rules for that user
        c.execute('DELETE FROM victim_rules WHERE victim_id=? AND room_id=?', (member, room_left))

    return event_success

def unmimic_user(mxid):
    # TODO have a "multi" version of the leave notification...
    event_success = True
    c = utils.get_db_conn().cursor()
    for row in c.execute('SELECT room_id FROM mimic_rules WHERE mxid=?', (mxid,)):
        event_success = user_leave_room(mxid, row[0]) and event_success

    return event_success


def prepend_with_author(message, author, isHTML):
    return '{0} says:{2}{1}'.format(author, message, '\n\n' if not isHTML else '<br><br>')


@app.route('/transactions/<int:txnId>', methods=['PUT'])
def transactions(txnId):
    response = validate_hs_token(request.args)
    if response is not None:
        return response

    # Assume success until failure
    txn_success = True

    committed_event_idxs = get_committed_txn_event_idxs(txnId)
    events = request.get_json()['events']
    for i in range(len(events)):

        if len(committed_event_idxs) > 0 and i == committed_event_idxs[0]:
            committed_event_idxs.pop(0)
            continue

        # Assume success until failure
        event_success = True

        event = events[i]
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
            room_id = event['room_id']

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
                            c.execute('INSERT INTO rooms VALUES (?, 0)', (room_id,))
                            event_success = find_or_prepare_control_room(sender) != None

                        if event_success and not refused:
                            # TODO non-blocking?
                            r = mx_request('POST', f'/_matrix/client/r0/rooms/{room_id}/join')
                            if r.status_code != 200:
                                event_success = False

                elif membership == 'join':
                    if utils.get_from_dict(event, 'prev_content', 'membership') == 'join':
                        # Do nothing if this is a repeat of a previous join event
                        pass

                    else:
                        in_control_room = get_in_control_room(room_id)
                        if in_control_room == None:
                            # Only possibility is that the bot somehow joined a room it didn't know about.
                            # Just leave.
                            event_success = bot_leave_room(room_id)

                        elif in_control_room:
                            if member == config.as_botname:
                                # TODO non-blocking
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
                                        messages.invalid_control_room_user(member, control_room_user))

                        else:
                            if member == config.as_botname:
                                # Notify each present listening user that the bot joined this room.
                                # A listening user is a user with a control room.
                                room_users = get_listening_room_users(room_id, [config.as_botname])
                                if room_users != None:
                                    room_name = get_room_name(room_id)
                                    if room_name == None:
                                        event_success = False
                                    else:
                                        for room_member in room_users:
                                            event_success = control_room_notify(
                                                room_member, room_id,
                                                notify_bot_joined, room_name) and event_success
                                else:
                                    event_success = False

                            else:
                                # Notify the user that they joined a room that the bot is in.
                                event_success = control_room_notify(
                                    member, room_id,
                                    notify_user_joined)

                elif membership == 'leave':
                    in_control_room = get_in_control_room(room_id)
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
                                room_name = get_room_name(room_id)
                                if room_name == None:
                                    event_success = False
                                else:
                                    for room_member in room_users:
                                        event_success = control_room_notify(
                                            room_member, room_id,
                                            notify_bot_left, room_name) and event_success
                            else:
                                event_success = False

                        # NOTE This should trigger a lot of cascaded deletions!
                        c.execute('DELETE FROM rooms WHERE room_id=?', (room_id,))

                    else:
                        if in_control_room:
                            if member == control_room_user:
                                # User left their control room or rejected an invite.
                                # Bot should leave the room too. Its leave event will handle the rest.
                                event_success = bot_leave_room(room_id) and event_success
                        else:
                            event_success = user_leave_room(member, room_id)
                            event_success = control_room_notify(
                                member, room_id,
                                notify_user_left) and event_success

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

                            if room_empty and event_success:
                                event_success = bot_leave_room(room_id)


            elif stype == 'message':
                if 'body' not in content:
                    # Event is redacted, ignore
                    pass
                elif get_in_control_room(room_id):
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
                        access_token = None
                        c.execute('SELECT * FROM generated_messages WHERE event_id=? AND room_id=?', (event['event_id'], room_id))
                        if c.fetchone() == None:
                            c.execute('SELECT access_token, mxid, replace FROM victim_rules NATURAL JOIN mimic_rules NATURAL JOIN user_access_tokens WHERE victim_id=? AND room_id=?', (sender, room_id))
                            row = c.fetchone()
                            if row != None:
                                access_token, mimic_user, replace = row

                        if access_token != None:
                            content['body'] = prepend_with_author(content['body'], sender, False)
                            if 'formatted_body' in content:
                                content['formatted_body'] = prepend_with_author(content['formatted_body'], sender, True)

                            r = mx_request('PUT',
                                    f'/_matrix/client/r0/rooms/{room_id}/send/m.room.message/txnId',
                                    json=content,
                                    access_token=access_token)

                            if r.status_code == 200:
                                c.execute('INSERT INTO generated_messages VALUES (?, ?)', (r.json()['event_id'], room_id))
                                if replace:
                                    r = mx_request('PUT',
                                        f'/_matrix/client/r0/rooms/{room_id}/redact/{event["event_id"]}/txnId',
                                        json={'reason':'Replaced by ImposterBot'})
                                    if r.status_code not in [200, 403, 404]:
                                        event_success = False

                            elif r.json()['errcode'] == 'M_UNKNOWN_TOKEN':
                                event_success = control_room_notify(
                                    mimic_user, room_id,
                                    notify_expired_token)
                            else:
                                # Unknown token is a "valid" error. For anything else, want to retry
                                event_success = False

            else:
                print(f'Unsupported room event type: {type}')
        else:
            print(f'Unsupported event type: {type}')

        if event_success:
            commit_txn_event(txnId, i)
        else:
            print('\nEvent unsuccessful!!!!!')
            txn_success = False
            # Discard any uncommitted changes
            utils.close_db_conn()

    return ({}, 200 if txn_success else 500)
