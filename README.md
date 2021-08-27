# matrix-imposter-bot
A [Matrix](https://matrix.org/) bot for relaying messages.

It works by monitoring all messages sent in rooms that it's present in, and re-posting those messages as if they were sent by a user whose access token the bot was given.

The purpose of this is to give relay-bot capabilities to puppeting-only bridges. The idea is to let the bot send messages from a Matrix account that is signed in to a puppeting bridge.

## Installation
* Clone this repository and `cd` to it.
* (Optional, but recommended) Create a Python virtual environment (like with `python3 -m venv .venv`), and activate it (`source .venv/bin/activate`).
* Install requirements with `pip install -r requirements.txt`.
* Copy `example-config.yaml` to `config.yaml` and edit at least the `homeserver` section to refer to your homeserver's domain. You may also set `avatar` to a `mxc://` URI of an image to be used as the bot user's avatar.
* Copy `example-registration.yaml` to `registration.yaml` and update `as_token` and `hs_token` with hard-to-guess values (such as the output of `pwgen -s 64 1`).
* Edit your homeserver's configuration to add this as a registered appservice. If using Synapse, edit your `homeserver.yaml` to contain the path of your `registration.yaml` file as one of the `app_service_config_files`.
* Run the appservice with `python3 -m matrix_imposter_bot`.

## Usage
The bot tries to walk you through how to set it up, but here are the starting steps:

* Invite the bot to a direct chat (its default username is `@_imposter_bot:your_domain`). This is your "control room" where you send commands to the bot.
* The bot will ask you for your access token, which it needs in order to work. (You can find your access token in Riot/Web under Settings->Help & About). Give the bot your token with a command of `token <your-token>`.
* Invite the bot to a room where you want it to use your account to repeat other people's messages, then say "mimicme" in your control room with the bot.

A `help` command is available as well, which explains other commands. The most important is `blacklist`, which accepts one or more patterns of Matrix user IDs to *not* repeat messages for.

## Example use case
This bot can be used to give relay-bot capabilities to the [mautrix-facebook](https://github.com/mautrix/facebook) bridge, with a few tweaks to that bridge. This means that Matrix users not logged into the mautrix-facebook bridge can participate in portal rooms bridged to Facebook chats.

* Use [this fork](https://github.com/mrjohnson22/mautrix-facebook/tree/outbound-only-rebased) of mautrix-facebook (or clone the original bridge and use the fork as a remote), which allows the usage of "outbound-only" accounts that can send (but not receive) messages from a Facebook account that another Matrix user is already logged in as.
* In your mautrix-facebook config, set `allow_invites` to `true`, which allows you to invite arbitrary Matrix users to portal rooms managed by the bridge.
* Create an alt of your Matrix account.
* [Follow these steps](https://docs.mau.fi/bridges/python/facebook/authentication.html) to log into Facebook with both your main Matrix account and your alt account.
* With both accounts, join any portal rooms of Facebook chats you want to have relay support in.
* With your alt account:
  * Start a direct chat with `@_imposter_bot:your_domain`, and give it your alt account's access token.
  * In the direct chat with the bot, say `blacklist @your_main_account:your_domain @facebook_.+:your_domain @facebookbot:your_domain`. This prevents the bot from repeating messages from your main account & bot users representing Facebook users, which are already bridged properly, and messages from the bridge bot itself, which don't need to be relayed.
  * Invite `@_imposter_bot:your_domain` to all of the Facebook portal rooms you just joined.
  * In the direct chat with the bot, reply with `mimicme` for each portal room you joined.

You can now use your main account to invite & chat with other Matrix users rooms in Facebook portal rooms! Any messages sent by other Matrix users will be re-sent by your alt account, which means those messages will get bridged to Facebook. You and other Matrix users may set your alt account as an "ignored user" to avoid seeing duplicate messages (the original message and the reposted one).

At this point, it is also possible to plumb the room to other services via bridges that support both plumbing and relaying, such as [matrix-appservice-discord](https://github.com/Half-Shot/matrix-appservice-discord). Note that to prevent duplicate messages from being seen by those services, any other bridge acting as a relay-bot must be configured to blacklist messages sent by this bot. For matrix-appservice-discord, [this PR](https://github.com/Half-Shot/matrix-appservice-discord/pull/576) may be used to achieve that.
