from .apputils import get_link_fmt_pair

# TODO translations???

def welcome():
    return 'Hi! I\'m imposter-bot. Send me commands in this room.\nTo get started, give me your access token by saying "token <your-token-here>".'

def ping():
    return 'You called?'

def already_controlled():
    return 'You invited me to a direct chat room, but we already have this room, and I can only be in one direct chat at a time!'

def invalid_control_room_user(bad_user_info, good_user_info):
    return get_link_fmt_pair('Hey {}, you aren\'t allowed in here! This is {}\'s control room!', [bad_user_info, good_user_info])

def invalid_command():
    return 'Not a valid command!'

# TODO get command names from const vars

def ask_for_token():
    return 'You can give me your token by saying "token <your-token-here>".'

def offer_mimic():
    return 'Reply "mimicMe" to this message to make me post other people\'s messages on your behalf in that room.'

def offer_stop():
    return 'To make me stop, reply "stopit" to this message.'

def mimic_taken(room_info, user_info):
    return get_link_fmt_pair(
            'I am now mimicking {0} in the following room:\n{1}',
            [user_info, room_info])

def cant_mimic():
    return 'I can\'t mimic you until I have your access token! ' + ask_for_token()

def bot_joined(room_info):
    return get_link_fmt_pair('I just joined a room:\n{}\n{}', [room_info], offer_mimic())

def user_joined(room_info, mimic_user_info):
    return get_link_fmt_pair(
            'You just joined a room that I am present in:\n{}\n' + (offer_mimic() if not mimic_user_info.id else 'I am already mimicking {} in this room.'),
            [room_info, mimic_user_info])

def bot_left(room_info):
    return get_link_fmt_pair('I just left this room:\n{}\nMy reign of terror in that room is over. I won\'t alter messages in it anymore.', [room_info])

def mimic_user_left(room_info, mimic_user_info):
    return get_link_fmt_pair('I am no longer mimicking {0} in following room:\n{1}\nNo one\'s messages will appear as coming from them anymore. This means you can now ask me to mimic you in that room if you like!\n{2}', [mimic_user_info, room_info], offer_mimic())

def received_token():
    return 'Thanks for your access token! I can now mimic you. To make me revoke this token, say "revoke".\nTry saying "actions" to see a list of everything you can make me do.'

def invalid_token():
    return 'Invalid access token!!'

def revoked_token():
    return 'OK, I discarded the access token you gave me. If I was mimicking you anywhere, I won\'t anymore.'

def no_revoke_token():
    return 'You never gave me a token to revoke!'

def expired_token():
    return 'The token I have for your account is invalid. I can\'t mimic you until you give me a new, valid access token.\n' + ask_for_token()

def no_room():
    return 'I can only answer that command in response to a room that I am present in!'

def accepted_mimic(room_info):
    return get_link_fmt_pair('I am now mimicking you in {}!\n{}', [room_info], offer_stop())

def rejected_mimic(room_info, user_info):
    return get_link_fmt_pair('I can\'t mimic you in {}, because I am already mimicking {} in that room.', [room_info, user_info])

def already_mimic(room_info):
    return get_link_fmt_pair('I am already mimicking you in {}!', [room_info])

def stopped_mimic(room_info):
    return get_link_fmt_pair('Okay, I stopped mimicking you in {}.', [room_info])

def never_mimicked(room_info):
    return get_link_fmt_pair('I was never mimicking you in {}!', [room_info])

def replace_reminder():
    return ' Don\'t forget to give me a power level high enough to delete messages!'

def set_response_mode(replace):
    return 'I will now {} people\'s messages.{}'.format('echo' if not replace else 'replace', replace_reminder() if replace else '')

def set_response_mode_in_room(replace, room_info):
    return get_link_fmt_pair('I will now {1} people\'s messages in {0}, overriding your global preference.{2}', [room_info], 'echo' if not replace else 'replace', replace_reminder() if replace else '')

def same_response_mode(replace):
    return 'I was already {} people\'s messages!'.format('echoing' if not replace else 'replacing')

def same_response_mode_in_room(replace, room_info):
    return get_link_fmt_pair('I was already {1} people\'s messages in {0}!', [room_info], 'echoing' if not replace else 'replacing')

def invalid_mode():
    return 'Valid modes are "echo", "replace", or "default" (only for room-specific modes).'

def default_response_mode_in_room(room_info):
    return get_link_fmt_pair('I will now follow your global preference for how to handle people\'s messages in {}.{}', [room_info])

def same_default_response_mode_in_room(room_info):
    return get_link_fmt_pair('I was already following your global preference for how to handle people\'s messages in {}!', [room_info])

def set_blacklist():
    return 'Global blacklist applied. I will not monitor messages sent by anyone matching the provided pattern.'

def set_blacklist_in_room(room_info):
    return get_link_fmt_pair('Room-specific blacklist applied in {}. I will not monitor messages sent by anyone matching the provided pattern in that room.', [room_info])

def default_blacklist_in_room(room_info):
    return get_link_fmt_pair('I will now use your global blacklist for {} instead of a room-specific blacklist.', [room_info])

def same_default_blacklist_in_room(room_info):
    return get_link_fmt_pair('I was already using your global blacklist for {}!', [room_info])

def mimic_none_available():
    return 'There are no rooms where I can mimic you in!'

def mimic_available():
    return 'I can mimic you in the following rooms. Reply "mimicMe" to the room you mimic you in.'

def mimic_none():
    return 'I am not mimicking you in any rooms!'

def echo_none():
    return 'I am not echoing you in any rooms!'

def replace_none():
    return 'I am not replacing your messages in any rooms!'

def mimic_status():
    return 'I am mimicking you in the following rooms. Reply "stopit" to the room you want me to stop mimicking you in.'

def echo_status():
    return 'I am echoing you in the following rooms. Reply "stopit" to the room you want me to stop echoing you in.'

def replace_status():
    return 'I am replacing your messages in the following rooms. Reply "stopit" to the room you want me to stop replacing your messages in.'

def room_name(room_info):
    return get_link_fmt_pair('{}', [room_info])

def room_name_and_mimic_user(room_info, user_info):
    return get_link_fmt_pair('{}, as {}', [room_info, user_info])
