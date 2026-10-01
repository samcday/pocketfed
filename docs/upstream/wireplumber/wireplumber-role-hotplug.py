#!/usr/bin/env python3
"""Reproduce role-loopback hotplug in a private, hardware-free audio session."""
import argparse
import json
import os
import signal
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import wave

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('data_dir', nargs='?', type=Path,
                    help='candidate script directory; expects recovery')
parser.add_argument('--upstream-tree', type=Path,
                    help='use a complete upstream checkout built in build/')
parser.add_argument('--expect', choices=('stall', 'recovery'),
                    help='expected result (default: stall, or recovery with data_dir)')
parser.add_argument('--artifact-parent', type=Path, default=Path('/tmp'),
                    help='parent directory for private runtimes and logs')
args = parser.parse_args()
expect_recovery = args.expect == 'recovery' if args.expect else args.data_dir is not None
wp_data = Path('/usr/share/wireplumber')
wp_config = wp_data / 'wireplumber.conf'
role_config = wp_data / 'wireplumber.conf.d/media-role-nodes.conf'
wp_command = 'wireplumber'
phone_role = 'Phone'
if args.upstream_tree:
    args.upstream_tree = args.upstream_tree.resolve()
    wp_data = args.upstream_tree / 'src'
    wp_config = wp_data / 'config/wireplumber.conf'
    role_config = wp_data / 'config/wireplumber.conf.d.examples/media-role-nodes.conf'
    wp_command = str(args.upstream_tree / 'build/src/wireplumber')
    phone_role = 'Communication'

args.artifact_parent.mkdir(parents=True, exist_ok=True)
root = Path(tempfile.mkdtemp(prefix='wp-role-', dir=args.artifact_parent))
print('Artifacts:', root, flush=True)
for name in ('run', 'config', 'data', 'state', 'cache'):
    (root / name).mkdir(mode=0o700)
wpconf = root / 'config' / 'wireplumber'
wpconf.mkdir()
shutil.copy(wp_config, wpconf)
frags = wpconf / 'wireplumber.conf.d'
frags.mkdir()
shutil.copy(role_config, frags)
(frags / 'zz-isolate.conf').write_text('''
wireplumber.profiles = {
  main = {
    hardware.audio = disabled
    hardware.bluetooth = disabled
    hardware.video-capture = disabled
    support.logind = disabled
    support.reserve-device = disabled
    support.portal-permissionstore = disabled
    script.client.access-portal = disabled
  }
}
wireplumber.settings = {
  linking.pause-playback = false
}
''')
env = dict(os.environ)
env.update({
    'XDG_RUNTIME_DIR': str(root / 'run'),
    'PIPEWIRE_RUNTIME_DIR': str(root / 'run'),
    'PIPEWIRE_REMOTE': 'pipewire-0',
    'XDG_CONFIG_HOME': str(root / 'config'),
    'XDG_DATA_HOME': str(root / 'data'),
    'XDG_STATE_HOME': str(root / 'state'),
    'XDG_CACHE_HOME': str(root / 'cache'),
    'WIREPLUMBER_CONFIG_DIR': str(wpconf),
    'WIREPLUMBER_DATA_DIR': str(wp_data),
    'WIREPLUMBER_DEBUG': 's-linking:4',
})
if args.data_dir:
    env['WIREPLUMBER_DATA_DIR'] = str(args.data_dir.resolve()) + ':' + str(wp_data)
if args.upstream_tree:
    env['WIREPLUMBER_MODULE_DIR'] = str(args.upstream_tree / 'build/modules')

processes = []
logs = []
def spawn(args, name):
    log = (root / (name + '.log')).open('w')
    logs.append(log)
    p = subprocess.Popen(args, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    processes.append(p)
    return p

def run(*args):
    return subprocess.check_output(args, env=env, stderr=subprocess.STDOUT, timeout=8)

def snapshot(name):
    raw = run('pw-dump')
    (root / (name + '.json')).write_bytes(raw)
    graph = json.loads(raw)
    nodes = {o['id']: o.get('info', {}).get('props', {}) for o in graph if o['type'].endswith(':Node')}
    crosslinks, playerlinks = [], []
    for o in graph:
        if not o['type'].endswith(':Link'):
            continue
        i = o['info']
        src = nodes[i['output-node-id']].get('node.name', '')
        dst = nodes[i['input-node-id']].get('node.name', '')
        link = [src, dst, i['state']]
        if src.startswith('output.loopback.sink.role.') and dst.startswith('input.loopback.sink.role.'):
            crosslinks.append(link)
        if src == 'hotplug-test-player':
            playerlinks.append(link)
    print(name, json.dumps({'crosslinks': crosslinks, 'playerlinks': playerlinks}), flush=True)
    return graph, crosslinks, playerlinks

def create_sink():
    run('pw-cli', 'create-node', 'adapter', '{ factory.name = support.null-audio-sink node.name = hotplug-test-speaker node.description = "Test Speaker" media.class = Audio/Sink object.linger = true audio.position = [ FL FR ] priority.session = 2000 }')
    time.sleep(1)

try:
    pw = spawn(['pipewire'], 'pipewire')
    for _ in range(50):
        if (root / 'run' / 'pipewire-0').exists():
            break
        if pw.poll() is not None:
            raise RuntimeError('Private PipeWire failed to start')
        time.sleep(.1)
    create_sink()
    wp = spawn(['dbus-run-session', '--', wp_command], 'wireplumber')
    time.sleep(2)
    tone = root / 'silence.wav'
    with wave.open(str(tone), 'wb') as f:
        f.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
        f.writeframes(bytes(48000 * 4 * 60))
    player = spawn(['pw-play', '--properties', 'node.name=hotplug-test-player', str(tone)], 'player')
    time.sleep(1)
    initial, crosslinks, playerlinks = snapshot('initial')
    assert len(playerlinks) == 2 and all(l[2] == 'active' for l in playerlinks), 'Initial playback failed'
    for cycle in range(3 if expect_recovery else 1):
        g = json.loads(run('pw-dump'))
        sink_id = next(o['id'] for o in g if o.get('info', {}).get('props', {}).get('node.name') == 'hotplug-test-speaker')
        run('pw-cli', 'destroy', str(sink_id))
        time.sleep(2)
        snapshot('disconnected-' + str(cycle))
        create_sink()
        time.sleep(2)
        _, crosslinks, playerlinks = snapshot('reconnected-' + str(cycle))
        if expect_recovery:
            assert not crosslinks, 'Role mixers were chained'
            assert len(playerlinks) == 2 and all(l[2] == 'active' for l in playerlinks), 'Playback did not recover'
        else:
            assert crosslinks and not playerlinks, 'Baseline failure did not reproduce'
    if expect_recovery:
        phone_tone = root / 'phone-silence.wav'
        with wave.open(str(phone_tone), 'wb') as f:
            f.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
            f.writeframes(bytes(48000 * 4 * 2))
        phone = spawn(['pw-play', '--media-role', phone_role, '--properties', 'node.name=hotplug-test-phone', str(phone_tone)], 'phone')
        time.sleep(.5)
        phone_graph, crosslinks, playerlinks = snapshot('phone-active')
        assert not crosslinks, 'Phone playback chained role mixers'
        assert not any(l[2] == 'active' for l in playerlinks), 'Phone did not cork music'
        assert phone.wait(timeout=5) == 0, 'Phone playback did not complete'
        time.sleep(.5)
        _, crosslinks, playerlinks = snapshot('phone-finished')
        assert len(playerlinks) == 2 and all(l[2] == 'active' for l in playerlinks), 'Music did not resume after phone'
    print('Player exit:', player.poll(), flush=True)
    print('PASS: ' + ('3 hotplug cycles and phone priority/resumption' if expect_recovery else 'baseline stall reproduced'), flush=True)
finally:
    for p in reversed(processes):
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for p in reversed(processes):
        try:
            p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
    for log in logs:
        log.close()
