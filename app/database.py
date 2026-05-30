from supabase import create_client, Client
from app.config import settings

# Cliente con service key — para operaciones del backend (bypass RLS cuando necesario)
supabase: Client = create_client(
    settings.supabase_url,
    settings.supabase_service_key
)

# Cliente con anon key — para operaciones que deben respetar RLS del usuario
def get_user_client(jwt_token: str) -> Client:
    client = create_client(settings.supabase_url, settings.supabase_anon_key)
    client.postgrest.auth(jwt_token)
    return client