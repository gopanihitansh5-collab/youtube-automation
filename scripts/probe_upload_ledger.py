"""Manual encrypted store/CAS smoke. Prints no ledger contents or secrets."""
import copy,uuid
from src.private_upload_store import PrivateGitHubStore
from src.upload_ledger import UploadConflict

def main():
    store=PrivateGitHubStore()
    stale=PrivateGitHubStore()
    marker='provisioning-probe-'+uuid.uuid4().hex
    store.put(marker,{'type':'provisioning_smoke','version':1})
    if store.get(marker)!={'type':'provisioning_smoke','version':1}:raise UploadConflict('Ledger probe readback failed')
    try:stale.put(marker,{'type':'invalid_stale_write'})
    except UploadConflict:pass
    else:raise UploadConflict('Ledger stale-write check failed')
    print('Encrypted ledger write/readback passed; stale revision rejected. No upload performed.')
if __name__=='__main__':main()
