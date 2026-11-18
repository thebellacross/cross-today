"""Open a one-use, two-minute admin sign-in link without exposing the saved password."""
import sys
import webbrowser
from pathlib import Path
import requests
from keychain_credentials import credential
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from music.common import config

def main():
    url=config()['worker_url'].rstrip('/')
    if not url.startswith('https://'):raise SystemExit('The management service has not been deployed yet.')
    token=credential('ADMIN_TOKEN')
    if not token:raise SystemExit('The project admin credential is missing from the login Keychain.')
    r=requests.post(url+'/api/login-link',headers={'Authorization':'Bearer '+token},timeout=45)
    if not r.ok:raise SystemExit('Could not open management sign-in. Please try again.')
    webbrowser.open(url+'/admin#login='+r.json()['code'])
    print('Opened the protected management page. The one-use sign-in link expires in two minutes.')

if __name__=='__main__':main()
