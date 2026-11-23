"""Retry refused or unavailable HTTP calls while retaining each dispatch and response."""
import time
import os
from urllib.error import HTTPError
from study import model_call as dispatch,read_json,write_json

def unavailable(dest):
    path=dest/'error.json'
    if os.environ.get('PELICAN_RETAIN_REFUSALS')!='1' or not path.exists() or (dest/'response.json').exists():return False
    error=read_json(path)
    if error.get('http')!=400 or 'DataInspectionFailed' not in error.get('detail',''):return False
    review=any(part.startswith('review-') for part in dest.parts)
    write_json(dest/('unavailable-review.json' if review else 'unavailable-proposal.json'),{'reason':'Provider refused the original request. No substitute reply or repeat dispatch.'})
    return True

def model_call(folder,*args):
    for i in range(5):
        dest=folder if i==0 else folder/f'transport-retry-{i}'
        if unavailable(dest):return ''
        err=dest/'error.json'
        if err.exists() and not (dest/'response.json').exists() and read_json(err).get('http') in (429,502,503,504):
            if i==4:raise RuntimeError('Provider remained unavailable: '+str(dest))
            continue
        try:return dispatch(dest,*args)
        except HTTPError as exc:
            if unavailable(dest):return ''
            if exc.code not in (429,502,503,504) or i==4:raise
            time.sleep(min(30,4*(2**i)))
