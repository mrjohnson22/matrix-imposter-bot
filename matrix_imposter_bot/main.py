from traceback import format_exception

from flask import request

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
    print('\n!!!\nreceiving txnId = {}'.format(txnId))
    c = utils.get_db_conn().cursor()
    c.execute('SELECT event_idx FROM transactions_in WHERE txnId=(?)', (txnId,))
    ret = []
    for row in c.fetchall():
        ret.append(row[0])
    print('Events we saw already = {}'.format(ret))
    return ret

def commit_txn_event(txnId, event_idx):
    print('Successfully handled event #{} of txnId = {}'.format(event_idx, txnId))
    conn = utils.get_db_conn()
    conn.execute('INSERT INTO transactions_in VALUES (?, ?)', (txnId, event_idx))
    # This will commit everything done during the event!
    conn.commit()


def get_room_users(room_id, exclude_users=[]):
    r = mx_request('GET', '/_matrix/client/r0/rooms/{}/members?membership=join'.format(room_id))
    if r.status_code != 200:
        return None

    c = utils.get_db_conn().cursor()
    c.execute('SELECT mxid FROM ignoring_users');
    for row in c.fetchall():
        exclude_users.append(row[0])

    users = set()
    for member_event in r.json()['chunk']:
        users.add(member_event['state_key'])
    return users.difference(exclude_users)


def get_or_prepare_control_room(mxid):
    print('Get control room for ' + mxid)

    control_room = None
    c = utils.get_db_conn().cursor()
    c.execute('SELECT room_id FROM control_rooms WHERE mxid=?', (mxid,))
    control_room = utils.fetchone_single(c)

    if control_room == None:
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
            c.execute('INSERT INTO control_rooms VALUES (?, ?)', (mxid, control_room))

            # TODO non-blocking
            post_message(control_room, messages.welcome())

    print('Control room for {} is {}'.format(mxid, control_room if control_room != None else 'is MISSING!!'))
    return control_room


def control_room_notify(user_to, target_room, notify_fn, *args):
    c = utils.get_db_conn().cursor()
    c.execute('SELECT mxid FROM ignoring_users WHERE mxid=?', (user_to,));
    if c.fetchone() != None:
        # Do nothing, no error
        return True

    control_room = get_or_prepare_control_room(user_to)
    if control_room == None:
        return False

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

def get_mimic_user(target_room):
    return utils.fetchone_single(
        utils.get_db_conn().execute('SELECT mxid FROM mimic_rules WHERE room_id=?', (target_room,)))

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
    command_func = utils.get_from_dict(COMMANDS, command_word)
    if command_func == None:
        return post_message_status(control_room, messages.invalid_command())

    command_args = command[1:]
    is_room_command = len(signature(command_func).parameters) == 5

    if not is_room_command:
        return command_func(command_args, sender, control_room)
    else:
        c = utils.get_db_conn().cursor()
        if replied_event != None:
            c.execute('SELECT room_id FROM reply_links WHERE control_room=? AND event_id=?',
                (control_room, replied_event))
        else:
            c.execute('SELECT room_id FROM reply_links NATURAL JOIN latest_reply_link WHERE control_room=?',
                (control_room,))

        target_room = utils.fetchone_single(c)
        if target_room == None and len(command_args) >= 1:
            room_alias = command_args.pop(0).replace('#', '%23')
            r = mx_request('GET', '/_matrix/client/r0/directory/room/{}'.format(room_alias))
            if r.status_code == 200:
                target_room = r.json()['room_id']

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
        utils.get_db_conn().execute('INSERT INTO user_access_tokens VALUES (?, ?)',
            (sender, access_token))
        return post_message_status(control_room, messages.received_token())
    else:
        return post_message_status(control_room, messages.invalid_token())

def cmd_revoke_token(command_args, sender, control_room):
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
            room_users = get_room_users(target_room, [config.as_botname, sender])
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
            notify_accepted_echo, room_name)

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
        room_users = get_room_users(target_room, [config.as_botname, sender])
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

    c.execute('SELECT room_id FROM mimic_rules WHERE mxid=?', (sender,))
    mimic_room_infos = []
    for row in c.fetchall():
        room_id = row[0]
        room_name = get_room_name(room_id)
        if room_name == None:
            return False
        mimic_room_infos.append((room_id, room_name))

    c.execute('SELECT room_id FROM victim_rules WHERE victim_id=? AND replace=0', (sender,))
    echo_room_infos = []
    for row in c.fetchall():
        room_id = row[0]
        room_name = get_room_name(room_id)
        if room_name == None:
            return False
        echo_room_infos.append((room_id, room_name))

    c.execute('SELECT room_id FROM victim_rules WHERE victim_id=? AND replace=1', (sender,))
    replace_room_infos = []
    for row in c.fetchall():
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


COMMANDS = {
    'token':        cmd_register_token,
    'revoke':       cmd_revoke_token,
    'mimicme':      cmd_set_mimic_user,
    'echome':       cmd_set_echo_user,
    'replaceme':    cmd_set_replace_user,
    'stopit':       cmd_unset_user,
    'status':       cmd_show_status
}


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
                print('{}: {}'.format(key, event[key]))
        print('--- END  EVENT')

        if type.find('m.room') == 0:
            stype = type[7:]
            sender = event['sender']
            room_id = event['room_id']

            c = utils.get_db_conn().cursor()
            c.execute('SELECT * FROM control_rooms WHERE room_id=?', (room_id,))
            in_control_room = c.fetchone() != None

            if in_control_room and sender == config.as_botname:
                # Do nothing in response to the bot acting in a control room
                pass
            elif stype == 'member':
                member = event['state_key']
                membership = content['membership']

                # TODO map of memberships to functions

                if membership == 'invite':
                    if member == config.as_botname:
                        # TODO non-blocking?
                        r = mx_request('POST', '/_matrix/client/r0/rooms/{}/join'.format(room_id))
                        if r.status_code not in [200, 403]:
                            event_success = False

                elif membership == 'join':
                    if utils.get_from_dict(event, 'prev_content', 'membership') == 'join':
                        # Do nothing if this is a repeat of a previous join event
                        print('---------repeat join---------')
                        pass
                    elif not in_control_room:
                        if member == config.as_botname:
                            # for each user in room, send an invite message
                            room_users = get_room_users(room_id, [config.as_botname])
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
                            event_success = control_room_notify(
                                member, room_id,
                                notify_user_joined) and event_success

                elif membership == 'leave':
                    if member == config.as_botname:
                        if in_control_room:
                            # Bot was somehow removed from control room, so just forget about the room.
                            # A new one will be created the next time one is needed
                            c.execute('DELETE FROM control_rooms WHERE mxid=?', (sender,))
                        else:
                            # remove anything related to this room from the DB
                            c.execute('DELETE FROM mimic_rules WHERE room_id=?', (room_id,))
                            c.execute('DELETE FROM victim_rules WHERE room_id=?', (room_id,))

                            # for each user in room, say that bot left
                            room_users = get_room_users(room_id, [config.as_botname])
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
                    else:
                        rooms_left = []
                        if in_control_room:
                            # User left their control room or rejected an invite.
                            # Act as if they left all rooms they were monitored in, then don't bother them anymore.
                            c.execute('SELECT room_id FROM mimic_rules WHERE mxid=?', (member,))
                            for row in c.fetchall():
                                rooms_left.append(row[0])
                            c.execute('INSERT INTO ignoring_users VALUES (?)', (sender,))
                            c.execute('DELETE FROM user_access_tokens WHERE mxid=?', (sender,))
                        else:
                            rooms_left.append(room_id)

                        for room_left in rooms_left:
                            c.execute('DELETE FROM mimic_rules WHERE mxid=? AND room_id=?', (member, room_left))
                            if c.rowcount > 0:
                                # User was mimic target: remove all rules for the room
                                c.execute('DELETE FROM victim_rules WHERE room_id=?', (room_left,))
                                room_users = get_room_users(room_left, [config.as_botname, member])
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

                            event_success = control_room_notify(
                                member, room_left,
                                notify_user_left) and event_success

            elif stype == 'message':
                if 'body' not in content:
                    # Event is redacted, ignore
                    pass
                elif in_control_room:
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
                    if content['body'].find(config.as_botname) != -1:
                        c.execute('DELETE FROM ignoring_users WHERE mxid=?', (sender,))
                        if c.rowcount == 1:
                            # Reinvite user who left their control room
                            mx_request('POST',
                                    '/_matrix/client/r0/rooms/{}/invite'.format(get_or_prepare_control_room(sender)),
                                    json={'user_id':sender})
                        else:
                            post_message(get_or_prepare_control_room(sender), messages.ping())

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
                                    '/_matrix/client/r0/rooms/{}/send/{}/txnId'.format(
                                        room_id, 'm.room.message'),
                                    json=content,
                                    access_token=access_token)

                            if r.status_code == 200:
                                c.execute('INSERT INTO generated_messages VALUES (?, ?)', (r.json()['event_id'], room_id))
                                if replace:
                                    r = mx_request('PUT',
                                        '/_matrix/client/r0/rooms/{}/redact/{}/txnId'.format(
                                            room_id, event['event_id']),
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
                print('Unsupported room event type: {}'.format(type))
        else:
            print('Unsupported event type: {}'.format(type))

        if event_success:
            commit_txn_event(txnId, i)
        else:
            print('\nEvent unsuccessful!!!!!')
            txn_success = False
            # Discard any uncommitted changes
            utils.close_db_conn()

    return ({}, 200 if txn_success else 500)
