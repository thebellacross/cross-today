"""Official GitHub device flow with retrying HTTP transport, never prints tokens.

Public OAuth client ID verified from cli/cli internal/authflow/flow.go v2.105.0.
The project stores the verified credential in the macOS login Keychain. Official
gh commands receive it through GH_TOKEN only for the relevant child process.
"""
import json
import time
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from keychain_credentials import credential

root=Path(__file__).resolve().parents[1]
status_file=root/'.state/github-login-status.json'
def status(state,**fields):
    status_file.parent.mkdir(exist_ok=True)
    status_file.write_text(json.dumps({'state':state,'updated':time.time(),**fields}))
session=requests.Session()
session.headers['Accept']='application/json'
session.mount('https://',HTTPAdapter(max_retries=Retry(total=5,backoff_factor=1,allowed_methods=frozenset(['GET','POST']),status_forcelist=[429,500,502,503,504])))
existing=credential('GITHUB_TOKEN')
if existing:
    check=session.get('https://api.github.com/user',headers={'Authorization':'Bearer '+existing},timeout=30)
    if check.ok and check.json().get('login','').lower()=='thebellacross':
        status('connected',login='thebellacross',storage='macOS login Keychain')
        print('Connected and verified: thebellacross (existing Keychain authorization)',flush=True)
        raise SystemExit(0)
client='178c6fc778ccc68e1d6a'
r=session.post('https://github.com/login/device/code',data={'client_id':client,'scope':'repo workflow'},timeout=30);r.raise_for_status();device=r.json()
print('Open:',device['verification_uri'],flush=True)
print('One-time code:',device['user_code'],flush=True)
print('Authorize thebellacross only. No password or token is needed in chat.',flush=True)
deadline=time.monotonic()+device['expires_in'];interval=device['interval']
status('awaiting_authorization',expires_at=time.time()+device['expires_in'])
print('This request expires in '+str(device['expires_in']//60)+' minutes.',flush=True)
while time.monotonic()<deadline:
    time.sleep(interval)
    try:
        r=session.post('https://github.com/login/oauth/access_token',data={'client_id':client,'device_code':device['device_code'],'grant_type':'urn:ietf:params:oauth:grant-type:device_code'},timeout=30)
        r.raise_for_status();value=r.json()
    except requests.RequestException:
        continue
    if value.get('error')=='slow_down':interval+=5;continue
    if value.get('error')=='authorization_pending':continue
    token=value.get('access_token')
    if not token:
        error=value.get('error');safe_error=error if error in {'expired_token','access_denied','incorrect_device_code','incorrect_client_credentials','device_flow_disabled','unsupported_grant_type'} else 'unexpected_response'
        status('not_connected',reason=safe_error)
        raise SystemExit('GitHub authorization did not complete: '+safe_error+'. No credential was stored.')
    profile=session.get('https://api.github.com/user',headers={'Authorization':'Bearer '+token},timeout=30);profile.raise_for_status();login=profile.json()['login']
    if login.lower()!='thebellacross':
        status('wrong_account')
        raise SystemExit('The authorized account was not thebellacross. No repository was created.')
    status('account_verified',login=login)
    # Save immediately in the OS credential store. gh's generic login validator
    # requires unrelated default scopes; project commands receive GH_TOKEN from
    # this narrowly scoped Keychain entry through their process environment.
    try:
        credential('GITHUB_TOKEN',token)
        if credential('GITHUB_TOKEN')!=token:raise RuntimeError('Credential read-back failed.')
    except RuntimeError:
        status('credential_storage_failed',login=login)
        raise SystemExit('The macOS login Keychain could not save this authorization. No token was printed.')
    status('connected',login=login,storage='macOS login Keychain')
    print('Connected and verified: '+login,flush=True)
    break
else:
    status('not_connected',reason='expired_token')
    raise SystemExit('Device authorization expired.')
