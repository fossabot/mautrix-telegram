# -*- coding: future_fstrings -*-
# mautrix-telegram - A Matrix-Telegram puppeting bridge
# Copyright (C) 2018 Tulir Asokan
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
import random
import string

yaml = YAML()
yaml.indent(4)


class DictWithRecursion:
    def __init__(self, data=None):
        self._data = data or CommentedMap()

    def _recursive_get(self, data, key, default_value):
        if '.' in key:
            key, next_key = key.split('.', 1)
            next_data = data.get(key, CommentedMap())
            return self._recursive_get(next_data, next_key, default_value)
        return data.get(key, default_value)

    def get(self, key, default_value, allow_recursion=True):
        if allow_recursion and '.' in key:
            return self._recursive_get(self._data, key, default_value)
        return self._data.get(key, default_value)

    def __getitem__(self, key):
        return self.get(key, None)

    def _recursive_set(self, data, key, value):
        if '.' in key:
            key, next_key = key.split('.', 1)
            if key not in data:
                data[key] = CommentedMap()
            next_data = data.get(key, CommentedMap())
            self._recursive_set(next_data, next_key, value)
            return
        data[key] = value

    def set(self, key, value, allow_recursion=True):
        if allow_recursion and '.' in key:
            self._recursive_set(self._data, key, value)
            return
        self._data[key] = value

    def __setitem__(self, key, value):
        self.set(key, value)

    def _recursive_del(self, data, key):
        if '.' in key:
            key, next_key = key.split('.', 1)
            if key not in data:
                return
            next_data = data[key]
            self._recursive_del(next_data, next_key)
            return
        try:
            del data[key]
        except KeyError:
            pass

    def delete(self, key, allow_recursion=True):
        if allow_recursion and '.' in key:
            self._recursive_del(self._data, key)
            return
        try:
            del self._data[key]
        except KeyError:
            pass

    def __delitem__(self, key):
        self.delete(key)

    def comment(self, key, message):
        indent = key.count(".") * 4
        try:
            path, key = key.rsplit(".", 1)
        except ValueError:
            path = None
        entry = self[path] if path else self._data
        c = self._data.ca.items.setdefault(key, [None, [], None, None])
        c[1] = []
        entry.yaml_set_comment_before_after_key(key=key, before=message, indent=indent)


class Config(DictWithRecursion):
    def __init__(self, path, registration_path):
        super().__init__()
        self.path = path
        self.registration_path = registration_path
        self._registration = None

    def load(self):
        with open(self.path, 'r') as stream:
            self._data = yaml.load(stream)

    def save(self):
        with open(self.path, 'w') as stream:
            yaml.dump(self._data, stream)
        if self._registration and self.registration_path:
            with open(self.registration_path, 'w') as stream:
                yaml.dump(self._registration, stream)

    @staticmethod
    def _new_token():
        return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(64))

    def update_0_1(self):
        permissions = self["bridge.permissions"] or CommentedMap()
        for entry in self["bridge.whitelist"] or []:
            permissions[entry] = "full"
        for entry in self["bridge.admins"] or []:
            permissions[entry] = "admin"

        self["bridge.permissions"] = permissions
        del self["bridge.whitelist"]
        del self["bridge.admins"]

        self["bridge.authless_relaybot_portals"] = self.get("bridge.authless_relaybot_portals",
                                                            True)
        self.comment("bridge.authless_relaybot_portals",
                     "Whether or not to allow creating portals from Telegram.")

        self.comment("bridge.permissions", "\n".join((
            "",
            "Permissions for using the bridge.",
            "Permitted values:",
            "  relaybot - Only use the bridge via the relaybot, no access to commands.",
            "      full - Full access to use the bridge via relaybot or logging in with Telegram account.",
            "     admin - Full access to use the bridge and some extra administration commands.",
            "Permitted keys:",
            "       * - All Matrix users",
            "  domain - All users on that homeserver",
            "    mxid - Specific user")))
        # The telegram section comment disappears for some reason 3:
        self.comment("telegram", "\nTelegram config")

        self["version"] = 1
        # Add newline before version
        self.comment("version",
                     "\nThe version of the config. The bridge will read this and automatically "
                     "update the config if\nthe schema has changed. For the latest version, "
                     "check the example config.")

    def check_updates(self):
        if self.get("version", 0) == 0:
            self.update_0_1()
        else:
            return
        self.save()

    def _get_permissions(self, key):
        level = self["bridge.permissions"].get(key, "")
        admin = level == "admin"
        whitelisted = level == "full" or admin
        relaybot = level == "relaybot" or whitelisted
        return relaybot, whitelisted, admin

    def get_permissions(self, mxid):
        permissions = self["bridge.permissions"] or {}
        if mxid in permissions:
            return self._get_permissions(mxid)

        homeserver = mxid[mxid.index(":") + 1:]
        if homeserver in permissions:
            return self._get_permissions(homeserver)

        return self._get_permissions("*")

    def generate_registration(self):
        homeserver = self["homeserver.domain"]

        username_format = self.get("bridge.username_template", "telegram_{userid}") \
            .format(userid=".+")
        alias_format = self.get("bridge.alias_template", "telegram_{groupname}") \
            .format(groupname=".+")

        self.set("appservice.as_token", self._new_token())
        self.set("appservice.hs_token", self._new_token())

        url = (f"{self['appservice.protocol']}://"
               f"{self['appservice.hostname']}:{self['appservice.port']}")
        self._registration = {
            "id": self.get("appservice.id", "telegram"),
            "as_token": self["appservice.as_token"],
            "hs_token": self["appservice.hs_token"],
            "namespaces": {
                "users": [{
                    "exclusive": True,
                    "regex": f"@{username_format}:{homeserver}"
                }],
                "aliases": [{
                    "exclusive": True,
                    "regex": f"#{alias_format}:{homeserver}"
                }]
            },
            "url": url,
            "sender_localpart": self["appservice.bot_username"],
            "rate_limited": False
        }
