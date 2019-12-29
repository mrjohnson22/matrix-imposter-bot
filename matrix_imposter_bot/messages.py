from .apputils import get_link_fmt_pair

# TODO translations???

def welcome():
    return 'Hi! I\'m imposter-bot. Send me commands in this room.\nTry saying "actions" to see a list of everything you can make me do.'

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

def offer_victim_template(position):
    return f'If you want me to make {{{position}}} send replicas of your messages, reply "echoMe" to this message.\nIf you want me to replace your messages with ones sent by {{{position}}}, reply "replaceMe" instead.'

def offer_stop():
    return 'To make me stop, reply "stopit" to this message.'

def mimic_taken(room_info, user_info):
    return get_link_fmt_pair(
            'I am now mimicking {0} in the following room:\n{1}\n' + offer_victim_template(0),
            [user_info, room_info])

def cant_mimic():
    return 'I can\'t mimic you until I have your access token! ' + ask_for_token()

def bot_joined(room_info):
    return get_link_fmt_pair('I just joined a room:\n{}\n{}', [room_info], offer_mimic())

def user_joined(room_info, mimic_user_info):
    return get_link_fmt_pair(
            'You just joined a room that I am present in:\n{0}\n' + (offer_mimic() if not mimic_user_info.id else offer_victim_template(1)),
            [room_info, mimic_user_info])

def bot_left(room_info):
    return get_link_fmt_pair('I just left this room:\n{}\nMy reign of terror in that room is over. I won\'t alter messages in it anymore.', [room_info])

def user_left(room_info):
    return get_link_fmt_pair('You just left a room that I was monitoring:\n{}', [room_info])

def mimic_user_left(room_info, mimic_user_info):
    return get_link_fmt_pair('I am no longer mimicking {0} in following room:\n{1}\nNo one\'s messages will appear as coming from them anymore. This means you can now ask me to mimic you in that room if you like!\n{2}', [mimic_user_info, room_info], offer_mimic())

def received_token():
    return 'Thanks for your access token! I can now mimic you.\nTo make me revoke this token, say "revoke".'

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

def accepted_echo(room_info):
    return get_link_fmt_pair('I am now echoing your messages in {}!\n{}', [room_info], offer_stop())

def accepted_replace(room_info):
    return get_link_fmt_pair('I am now replacing your messages in {}!\nJust remember that I can only delete messages if I have sufficient administrative privileges in that room. If your messages don\'t get replaced, ask the admin(s) of the room to give me permission to delete messages in that room.\n{}', [room_info], offer_stop())

def cannot_victimize(room_info):
    return get_link_fmt_pair('I am not mimicking anyone in {}. I can only echo your messages in rooms where I\'m mimicking someone!', [room_info])

def cannot_victimize_yourself(room_info):
    return get_link_fmt_pair('I am already mimicking you in {}. I can\'t echo and mimic you at the same time!', [room_info])

def rejected_mimic(room_info, user_info):
    return get_link_fmt_pair('I can\'t mimic you in {}, because I am already mimicking {} in that room.', [room_info, user_info])

def already_mimic(room_info):
    return get_link_fmt_pair('I am already mimicking you in {}!', [room_info])

def stopped_mimic(room_info):
    return get_link_fmt_pair('Okay, I stopped mimicking you in {}.', [room_info])

def stopped_victim(room_info):
    return get_link_fmt_pair('Okay, I stopped listening to your messages in {}.', [room_info])

def missed_listen(room_info):
    return get_link_fmt_pair('I was never listening to you in {}!', [room_info])

def mimic_none_available():
    return 'There are no rooms where I can mimic you in!'

def victim_none_available():
    return 'There are no rooms where I can echo you or replace your messages in!'

def mimic_available():
    return 'I can mimic you in the following rooms. Reply "mimicMe" to the room you mimic you in.'

def victim_available():
    return 'I can echo you or replace your messages in the following rooms. Reply "echoMe" or "replaceMe" to the room you want me to echo/replace you in.'

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
