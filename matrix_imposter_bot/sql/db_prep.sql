CREATE TABLE IF NOT EXISTS user_access_tokens (
    mxid text NOT NULL,
    access_token text NOT NULL,

    PRIMARY KEY (mxid, access_token)
        ON CONFLICT REPLACE
);

CREATE TABLE IF NOT EXISTS mimic_rules (
    mxid text NOT NULL,
    room_id text NOT NULL,

    PRIMARY KEY (mxid, room_id),
    FOREIGN KEY (mxid)
        REFERENCES user_access_tokens (mxid)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS victim_rules (
    victim_id text NOT NULL,
    room_id text NOT NULL,
    replace integer NOT NULL CHECK (replace IN (0,1)),

    PRIMARY KEY (victim_id, room_id)
        ON CONFLICT REPLACE
);

CREATE TABLE IF NOT EXISTS generated_messages (
    event_id text NOT NULL,
    room_id text NOT NULL,

    PRIMARY KEY (event_id, room_id)
);

CREATE TABLE IF NOT EXISTS control_rooms (
    mxid text NOT NULL,
    room_id text NOT NULL,

    PRIMARY KEY (mxid)
);

CREATE TABLE IF NOT EXISTS ignoring_users (
    mxid text PRIMARY KEY NOT NULL
);

CREATE TABLE IF NOT EXISTS reply_links (
    control_room text NOT NULL,
    event_id text NOT NULL,
    room_id text NOT NULL,

    PRIMARY KEY (control_room, event_id),
    FOREIGN KEY (control_room)
        REFERENCES control_rooms (room_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS latest_reply_link (
    control_room text NOT NULL,
    event_id text NOT NULL,

    PRIMARY KEY (control_room)
        ON CONFLICT REPLACE,
    FOREIGN KEY (control_room, event_id)
        REFERENCES reply_links (control_room, event_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS transactions_in (
    txnId integer NOT NULL,
    event_idx integer NOT NULL,

    PRIMARY KEY (txnId, event_idx)
);

CREATE TABLE IF NOT EXISTS transactions_out (
    txnId integer PRIMARY KEY AUTOINCREMENT,
    committed integer NOT NULL CHECK (committed IN (0,1))
);
