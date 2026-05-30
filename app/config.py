from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    supabase_url: str
    supabase_anon_key: str
    supabase_service_key: str
    secret_key: str
    anthropic_api_key: str = ""  # Vacío por defecto, obligatorio en producción
    environment: str = "development"
    frontend_url: str = "http://localhost:5173"

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

try:
    settings = Settings()
except Exception as e:
    print(f"ERROR: Faltan variables de entorno requeridas. Por favor configura el archivo .env")
    print(f"Detalle: {e}")
    # En desarrollo, permitimos que importe pero fallará al usarlo, 
    # o podemos salir si es crítico. Aquí lanzamos un error más limpio.
    raise RuntimeError("Configuración incompleta. Revisa el archivo .env") from e
