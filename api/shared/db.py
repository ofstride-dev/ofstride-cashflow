import os
from supabase import create_client, Client

def get_supabase_client() -> Client:
    url = os.environ.get("SUPABASE_URL")
    service_role_key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_SERVICE_KEY")
    )
    
    if not url or not service_role_key:
        raise ValueError("Supabase credentials missing in environment variables.")
        
    return create_client(url, service_role_key)