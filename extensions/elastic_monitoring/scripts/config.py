"""Offline configuration checks. Reads a small, non-secret JSON object on stdin."""
import json
import re
import sys
from urllib.parse import urlsplit


def validate(config):
    if not isinstance(config, dict):
        raise ValueError('Configuration must be an object')
    expected = {'elastic_version', 'fleet_url', 'elasticsearch_url', 'kibana_url',
                'targets', 'min_free_gb', 'event_log_bytes', 'security_log_bytes'}
    if set(config) != expected:
        raise ValueError('Missing or unexpected configuration keys')
    if config['elastic_version'] != '9.5.3':
        raise ValueError('This milestone targets Elastic 9.5.3 only')
    for key in ('fleet_url', 'elasticsearch_url', 'kibana_url'):
        value = config[key]
        if not isinstance(value, str) or any(c.isspace() for c in value):
            raise ValueError(f'{key}: expected HTTPS URL without whitespace')
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment
                or parsed.path not in ('', '/')):
            raise ValueError(f'{key}: use an HTTPS origin without credentials or a base path')
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError(f'{key}: invalid port')
    targets = config['targets']
    if not isinstance(targets, list) or not targets:
        raise ValueError('targets must be a nonempty list of inventory aliases')
    if any(not isinstance(t, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', t)
           or t in ('all', 'localhost') for t in targets):
        raise ValueError('Use explicit inventory aliases, not patterns or localhost')
    if len(set(targets)) != len(targets):
        raise ValueError('Duplicate targets')
    if type(config['min_free_gb']) is not int or not 1 <= config['min_free_gb'] <= 1024:
        raise ValueError('min_free_gb must be an integer between 1 and 1024')
    for key in ('event_log_bytes', 'security_log_bytes'):
        value = config[key]
        if type(value) is not int or not 1048576 <= value <= 4294901760 or value % 65536:
            raise ValueError(f'{key}: use a 64-KiB multiple between 1 MiB and 4 GiB minus 64 KiB')
    return config


if __name__ == '__main__':
    try:
        validate(json.load(sys.stdin))
    except (ValueError, TypeError, KeyError) as exc:
        print(f'Invalid monitoring configuration: {exc}', file=sys.stderr)
        sys.exit(2)
    print('Monitoring configuration is valid; this is not an OS compatibility assertion.')
