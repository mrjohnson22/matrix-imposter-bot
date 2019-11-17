import re
import yaml


with open('registration.yaml') as reg_file:
    reg_settings = yaml.safe_load(reg_file)

with open('config.yaml') as cfg_file:
    cfg_settings = yaml.safe_load(cfg_file)


as_token = reg_settings['as_token']
hs_token = reg_settings['hs_token']

hs_address = cfg_settings['homeserver']['address']
hs_domain = cfg_settings['homeserver']['domain']

db_name = cfg_settings['appservice']['db_name']

as_botname = '@{}:{}'.format(reg_settings['sender_localpart'], hs_domain)
as_disname = cfg_settings['bot']['displayname']
as_avatar =  cfg_settings['bot']['avatar']
