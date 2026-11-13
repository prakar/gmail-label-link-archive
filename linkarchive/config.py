"""Configuration: accounts and labels (JSON), credentials (JSON, git-ignored), extraction profiles (TOML)."""
import json, os, stat, sys
from .extract import Profile

DEFAULT_DIR = 'config'


class Config:
    def __init__(self, config_dir=DEFAULT_DIR):
        self.dir = os.path.abspath(os.path.expanduser(config_dir))
        self.settings = self._json('accounts.json', required=True)
        self.title = self.settings.get('title', 'Link archive')
        self.out_dir = os.path.expanduser(self.settings.get('out_dir', '~/feeds'))
        self.data_dir = os.path.expanduser(self.settings.get('data_dir', '~/.local/share/gmail-label-link-archive'))
        self.base_url = self.settings.get('base_url', '')
        self.accounts = self.settings.get('accounts', [])
        self._profiles = {}

    def _json(self, name, required=False):
        path = os.path.join(self.dir, name)
        if not os.path.exists(path):
            if required: sys.exit(f'Missing {path}. Copy {name.replace(".json", ".example.json")} to {name} and edit it.')
            return {}
        with open(path, encoding='utf-8') as fh: return json.load(fh)

    def sources(self):
        """Every (account, label entry) pair, each label entry carrying its own 'source' id and 'profile' name."""
        return [(a, l) for a in self.accounts for l in a.get('labels', [])]

    def source(self, name):
        for a, l in self.sources():
            if l['source'] == name: return a, l
        sys.exit(f'No label with source "{name}" in accounts.json.')

    def profile(self, name):
        if name not in self._profiles:
            path = os.path.join(self.dir, 'profiles', name + '.toml')
            if not os.path.exists(path): sys.exit(f'Missing extraction profile {path}.')
            self._profiles[name] = Profile.load(path)
        return self._profiles[name]

    def password(self, account_name):
        """Reads credentials.json only when a command needs Gmail. Warns if other users can read the file."""
        path = os.path.join(self.dir, 'credentials.json')
        if not os.path.exists(path): sys.exit(f'Missing {path}. Copy credentials.example.json to credentials.json (and chmod 600 it).')
        if os.stat(path).st_mode & (stat.S_IRWXG | stat.S_IRWXO): print(f'Warning: {path} is readable by other users; run chmod 600 on it.', file=sys.stderr)
        with open(path, encoding='utf-8') as fh: pw = json.load(fh).get(account_name, {}).get('app_password', '')
        if not pw: sys.exit(f'No app_password for account "{account_name}" in credentials.json.')
        return pw.replace(' ', '')
