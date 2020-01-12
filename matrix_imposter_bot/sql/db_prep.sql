PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS rooms (
    room_id text PRIMARY KEY,
    mimic_user text
);

CREATE TABLE IF NOT EXISTS control_rooms (
    mxid text PRIMARY KEY,
    room_id text NOT NULL UNIQUE,
    access_token text
);

CREATE TABLE IF NOT EXISTS response_modes (
    mimic_user text NOT NULL,
    room_id text,
    replace integer CHECK (replace IN (0,1)),

    PRIMARY KEY (mimic_user, room_id),
    FOREIGN KEY (mimic_user)
        REFERENCES control_rooms (mxid)
        ON DELETE CASCADE,
    FOREIGN KEY (room_id)
        REFERENCES rooms (room_id)
        ON DELETE CASCADE
);

CREATE TRIGGER IF NOT EXISTS unique_null_response_modes
    BEFORE INSERT ON response_modes
    WHEN NEW.room_id IS NULL
    BEGIN
        SELECT CASE
        WHEN EXISTS (SELECT 1 FROM response_modes WHERE room_id IS NULL AND mimic_user=NEW.mimic_user)
        THEN RAISE(ABORT, 'Duplicate global entries') END;
    END;

CREATE TABLE IF NOT EXISTS blacklists (
    mimic_user text NOT NULL,
    room_id text,
    blacklist text,

    PRIMARY KEY (mimic_user, room_id) ON CONFLICT REPLACE,
    FOREIGN KEY (mimic_user)
        REFERENCES control_rooms (mxid)
        ON DELETE CASCADE,
    FOREIGN KEY (room_id)
        REFERENCES rooms (room_id)
        ON DELETE CASCADE
);

CREATE TRIGGER IF NOT EXISTS unique_null_blacklists
    BEFORE INSERT ON blacklists
    WHEN NEW.room_id IS NULL
    BEGIN
        DELETE FROM blacklists WHERE room_id IS NULL AND mimic_user=NEW.mimic_user;
    END;

CREATE TABLE IF NOT EXISTS generated_messages (
    event_id text NOT NULL,
    room_id text NOT NULL,

    PRIMARY KEY (event_id, room_id),
    FOREIGN KEY (room_id)
        REFERENCES rooms (room_id)
        ON DELETE CASCADE
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
    control_room text PRIMARY KEY ON CONFLICT REPLACE,
    event_id text NOT NULL,

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
    committed integer CHECK (committed IN (0,1))
);

