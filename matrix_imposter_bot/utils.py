import sqlite3

from flask import g
from requests import request
from requests.exceptions import ConnectionError

from time import sleep

from .config import db_name


def get_db_conn():
    if 'conn' not in g:
        g.conn = sqlite3.connect(db_name)
        g.conn.execute('PRAGMA foreign_keys = ON')

    return g.conn

def close_db_conn():
    conn = g.pop('conn', None)

    if conn != None:
        # Do not commit here! Other places should do it themselves
        conn.close()


def get_from_dict(dict, *keys):
    for key in keys[:-1]:
        if key in dict:
            dict = dict[key]
        else:
            return None
    return dict[keys[-1]] if keys[-1] in dict else None

def fetchone_single(c):
    seq = c.fetchone()
    return seq[0] if seq else None

def make_request(method, endpoint, json=None, headers=None, verbose=True, wait=False, **kwargs):
    if verbose:
        print('\n---BEGIN REQUEST')
        print('Method: ' + method)
        print('URL: ' + endpoint)
        #if headers != None:
        #    for key in headers:
        #        print(f'{key}: {headers[key]}')
        if json != None:
            for key in json:
                print(f'{key}: {json[key]}')
        print('--- END  REQUEST')

    while True:
        try:
            r = request(method, endpoint, json=json, headers=headers, **kwargs)
            break
        except ConnectionError as e:
            if verbose:
                print('Error, try again in 5 seconds...')
                sleep(5)

    if verbose:
        print('\n---BEGIN RESPONSE')
        try:
            json = r.json()
            for key in json:
                print(f'{key}: {json[key]}')
        except:
            print(r.text)

        print(f'STATUS: {r.status_code}')
        #print(r.headers.items())
        print('--- END  RESPONSE')

    return r
