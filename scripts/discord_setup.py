"""One-off: lay out the Last Shift Coffee Discord server (roles, channels, permissions, webhooks).

  python scripts/discord_setup.py [--dry-run] [--guild ID]

Discord no longer lets bots create servers, so make an empty one by hand first, invite the
setup bot with Administrator, and save its token to ~/.config/lastshift/discord-bot-token.
Safe to re-run: anything that already exists (matched by name) is left alone.

Writes the two webhook URLs to ~/.config/lastshift/discord-webhooks.env (mode 600), for the
DISCORD_WEEKLY_WEBHOOK and DISCORD_INSTANT_WEBHOOK GitHub secrets. Never prints tokens or webhook URLs.
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = 'https://discord.com/api/v10'
UA = 'DiscordBot (https://www.lastshiftcoffee.co.uk, 1.0)'
CONF = os.path.expanduser('~/.config/lastshift')
DRY = '--dry-run' in sys.argv

# Permission bits (developers/topics/permissions)
VIEW, SEND, REACT, MENTION_ALL = 1 << 10, 1 << 11, 1 << 6, 1 << 17
THREADS = (1 << 35) | (1 << 36) | (1 << 38)   # create public/private threads, send in threads
MOD = (1 << 1) | (1 << 2) | (1 << 13) | (1 << 34) | (1 << 40)   # kick, ban, manage messages/threads, timeout

ROLES = [
    {'name': 'Mod', 'permissions': str(MOD), 'hoist': True, 'colors': {'primary_color': 0xC0392B}},
    {'name': 'Drops Member', 'permissions': '0', 'hoist': True, 'colors': {'primary_color': 0x8B5A2B}},
]
# access: 'read' = everyone reads, nobody but mods/webhooks posts. 'members' = Drops Member only, read-only.
# 'members-chat' = Drops Member only, can talk. Anything else = open chat.
LAYOUT = [
    ('START HERE', [
        ('welcome', 'read', 'What this server is and how the drops work.'),
        ('rules', 'read', 'Keep it friendly and about coffee.'),
    ]),
    ('DROPS', [
        ('weekly-drops', 'read', 'Every Friday: the week\'s new coffees from UK roasters. Free.'),
        ('instant-drops', 'members', 'New coffees and restocks the moment they land. Drops Members only.'),
    ]),
    ('COFFEE CHAT', [
        ('general', 'chat', 'Anything coffee.'),
        ('whats-brewing', 'chat', 'Show us what is in your cup today.'),
        ('roaster-requests', 'chat', 'Which UK roasters should the drops bot watch?'),
    ]),
    ('MEMBERS', [
        ('members-chat', 'members-chat', 'For Drops Members. Thanks for keeping the lights on.'),
    ]),
]
MESSAGES = {
    'welcome': (
        "**Welcome to Last Shift Coffee**\n\n"
        "This is the home of Last Shift Coffee Drops. A bot checks UK speciality roasters every hour "
        "and posts new coffees and restocks here, with a link straight to the roaster.\n\n"
        "**#weekly-drops** is free: the week's new coffees, every Friday.\n"
        "**#instant-drops** is for Drops Members: every new coffee and restock as it happens. "
        "Join on Buy Me a Coffee and the role is added for you.\n\n"
        "Reviews live at https://www.lastshiftcoffee.co.uk"),
    'rules': (
        "**Rules**\n\n"
        "1. Be decent to each other.\n"
        "2. Keep it about coffee.\n"
        "3. No spam, no selling, no referral links. Roasters are welcome to say hello.\n"
        "4. Don't repost #instant-drops elsewhere. It's what members pay for.\n"
        "5. Mods have the final say."),
}
WEBHOOK_NAME = 'Last Shift Drops'
LOGO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'brand', 'avatar.png')


def api(method, path, body=None):
    token = open(os.path.join(CONF, 'discord-bot-token')).read().strip()
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Authorization': f'Bot {token}', 'User-Agent': UA,
                                          'Content-Type': 'application/json'})
    for _ in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read() or 'null')
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors='replace')
            if e.code == 429:
                time.sleep(json.loads(detail).get('retry_after', 2) + 0.5)
                continue
            sys.exit(f'{method} {path} failed: {e.code} {detail[:300]}')
    sys.exit(f'{method} {path}: still rate limited')


def write(method, path, body, label):
    print(('[dry run] ' if DRY else '') + label)
    return None if DRY else api(method, path, body)


def main():
    me = api('GET', '/users/@me')
    guilds = api('GET', '/users/@me/guilds')
    gid = sys.argv[sys.argv.index('--guild') + 1] if '--guild' in sys.argv else None
    if not gid:
        if len(guilds) != 1:
            sys.exit(f'Bot is in {len(guilds)} servers, pass --guild ID: ' + ', '.join(f"{g['name']} {g['id']}" for g in guilds))
        gid = guilds[0]['id']
    guild = api('GET', f'/guilds/{gid}')
    print(f"Bot {me['username']} setting up server: {guild['name']}")

    # Roles. @everyone shares the server's id and loses @everyone/@here pings.
    roles = {r['name']: r for r in api('GET', f'/guilds/{gid}/roles')}
    everyone = roles['@everyone']
    if int(everyone['permissions']) & MENTION_ALL:
        write('PATCH', f'/guilds/{gid}/roles/{gid}', {'permissions': str(int(everyone['permissions']) & ~MENTION_ALL)},
              '@everyone: remove @everyone/@here pings')
    for role in ROLES:
        if role['name'] not in roles:
            roles[role['name']] = write('POST', f'/guilds/{gid}/roles', role, f"role: {role['name']}") or {'id': '0'}
    member, mod = roles['Drops Member']['id'], roles['Mod']['id']

    def overwrites(access):
        if access == 'read':
            return [{'id': gid, 'type': 0, 'allow': str(VIEW | REACT), 'deny': str(SEND | THREADS)},
                    {'id': mod, 'type': 0, 'allow': str(SEND), 'deny': '0'}]
        if access == 'members':
            return [{'id': gid, 'type': 0, 'allow': '0', 'deny': str(VIEW)},
                    {'id': member, 'type': 0, 'allow': str(VIEW | REACT), 'deny': str(SEND | THREADS)},
                    {'id': mod, 'type': 0, 'allow': str(VIEW | SEND), 'deny': '0'}]
        if access == 'members-chat':
            return [{'id': gid, 'type': 0, 'allow': '0', 'deny': str(VIEW)},
                    {'id': member, 'type': 0, 'allow': str(VIEW | SEND | REACT), 'deny': '0'},
                    {'id': mod, 'type': 0, 'allow': str(VIEW | SEND), 'deny': '0'}]
        return []

    # Channels
    existing = {(c['name'], c['type']): c for c in api('GET', f'/guilds/{gid}/channels')}
    chans = {}
    for cat_name, channels in LAYOUT:
        cat = existing.get((cat_name.lower(), 4)) or existing.get((cat_name, 4))
        if not cat:
            cat = write('POST', f'/guilds/{gid}/channels', {'name': cat_name, 'type': 4}, f'category: {cat_name}') or {'id': None}
        for name, access, topic in channels:
            old = existing.get((name, 0))
            if old and cat['id'] and old.get('parent_id') != cat['id']:   # e.g. Discord's own #general
                write('PATCH', f"/channels/{old['id']}", {'parent_id': cat['id'], 'topic': topic}, f'#{name}: move into {cat_name}')
            chans[name] = old or write(
                'POST', f'/guilds/{gid}/channels',
                {'name': name, 'type': 0, 'topic': topic, 'parent_id': cat['id'], 'permission_overwrites': overwrites(access)},
                f'#{name} ({access})') or {'id': None}

    # Server settings: verified email + 5 min account age, scan all media, notify on mentions only
    logo = 'data:image/png;base64,' + base64.b64encode(open(LOGO, 'rb').read()).decode()
    write('PATCH', f'/guilds/{gid}', {'icon': logo, 'verification_level': 2, 'explicit_content_filter': 2,
                                      'default_message_notifications': 1, 'system_channel_id': chans['general']['id']},
          'server: lamp logo icon, verification medium, media filter all members, mentions-only notifications, system messages in #general')

    if DRY:
        print('[dry run] welcome/rules messages, 2 webhooks, invite link')
        return

    # Welcome and rules text, only into empty channels
    for name, text in MESSAGES.items():
        if not api('GET', f"/channels/{chans[name]['id']}/messages?limit=1"):
            api('POST', f"/channels/{chans[name]['id']}/messages", {'content': text})
            print(f'posted #{name} message')

    # Webhooks for the drops bot
    env = {}
    for name, var in (('weekly-drops', 'DISCORD_WEEKLY_WEBHOOK'), ('instant-drops', 'DISCORD_INSTANT_WEBHOOK')):
        cid = chans[name]['id']
        hook = next((h for h in api('GET', f'/channels/{cid}/webhooks') if h['name'] == WEBHOOK_NAME), None)
        hook = hook or api('POST', f'/channels/{cid}/webhooks', {'name': WEBHOOK_NAME, 'avatar': logo})
        env[var] = f"https://discord.com/api/webhooks/{hook['id']}/{hook['token']}"
        print(f'webhook ready: #{name}')
    path = os.path.join(CONF, 'discord-webhooks.env')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(''.join(f'{k}={v}\n' for k, v in env.items()))
    print(f'webhook URLs saved to {path}')

    invite = api('POST', f"/channels/{chans['welcome']['id']}/invites", {'max_age': 0, 'max_uses': 0, 'unique': False})
    print(f"invite link (public, for the /drops/ page): https://discord.gg/{invite['code']}")


if __name__ == '__main__':
    main()
