"""Almacenamiento de archivos del expediente: carpeta local (demo) o Supabase Storage (bucket privado)."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from core import config

BUCKET = "expedientes"


class AlmacenLocal:
    nombre = "carpeta local (modo demo)"

    def __init__(self, raiz: Path | None = None):
        self.raiz = Path(raiz or (config.dir_datos() / "expedientes"))
        self.raiz.mkdir(parents=True, exist_ok=True)

    def _p(self, ruta: str) -> Path:
        p = (self.raiz / ruta).resolve()
        if self.raiz.resolve() not in p.parents:
            raise ValueError("Ruta inválida")
        return p

    def guardar(self, ruta: str, datos: bytes, mime: str | None = None) -> None:
        p = self._p(ruta)
        if p.exists():
            raise FileExistsError("Los documentos no se reemplazan: se agrega una versión nueva.")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(datos)

    def leer(self, ruta: str) -> bytes:
        return self._p(ruta).read_bytes()

    def listar(self, prefijo: str = "") -> list[str]:
        """Rutas (relativas a la raíz) de todos los archivos bajo el prefijo, ordenadas."""
        base = self._p(prefijo) if prefijo else self.raiz.resolve()
        if not base.exists():
            return []
        return sorted(p.relative_to(self.raiz.resolve()).as_posix() for p in base.rglob("*") if p.is_file())

    def enlace_temporal(self, ruta: str, segundos: int = 300) -> str | None:
        return None


class AlmacenSupabase:
    nombre = "Supabase Storage (bucket privado «expedientes»)"

    def __init__(self, url: str | None = None, llave: str | None = None, bucket: str = BUCKET):
        import httpx
        self.url = (url or config.obtener("SUPABASE_URL")).rstrip("/")
        llave = llave or config.obtener("SUPABASE_SERVICE_KEY")
        self.bucket = bucket
        self.http = httpx.Client(timeout=60, headers={"apikey": llave, "Authorization": f"Bearer {llave}"})

    def _u(self, ruta: str) -> str:
        return f"{self.url}/storage/v1/object/{self.bucket}/{quote(ruta)}"

    def guardar(self, ruta: str, datos: bytes, mime: str | None = None) -> None:
        r = self.http.post(self._u(ruta), content=datos,
                           headers={"Content-Type": mime or "application/octet-stream", "x-upsert": "false"})
        if r.status_code == 409 or (r.status_code == 400 and "uplicate" in r.text):
            raise FileExistsError("Los documentos no se reemplazan: se agrega una versión nueva.")
        if r.status_code >= 300:
            raise IOError(f"No se pudo guardar el archivo en Supabase Storage ({r.status_code}): {r.text[:200]}")

    def leer(self, ruta: str) -> bytes:
        r = self.http.get(self._u(ruta))
        if r.status_code >= 300:
            raise IOError(f"No se pudo leer el archivo ({r.status_code}).")
        return r.content

    def listar(self, prefijo: str = "") -> list[str]:
        """Rutas de todos los archivos bajo el prefijo (recorre el bucket; las entradas sin id son carpetas)."""
        prefijo = prefijo.strip("/")
        rutas, offset = [], 0
        while True:
            r = self.http.post(f"{self.url}/storage/v1/object/list/{self.bucket}",
                               json={"prefix": prefijo, "limit": 1000, "offset": offset,
                                     "sortBy": {"column": "name", "order": "asc"}})
            if r.status_code >= 300:
                raise IOError(f"No se pudo listar el almacenamiento ({r.status_code}).")
            lote = r.json()
            for e in lote:
                ruta = f"{prefijo}/{e['name']}" if prefijo else e["name"]
                if e.get("id") is None:
                    rutas += self.listar(ruta)
                else:
                    rutas.append(ruta)
            if len(lote) < 1000:
                return sorted(rutas)
            offset += 1000

    def enlace_temporal(self, ruta: str, segundos: int = 300) -> str | None:
        r = self.http.post(f"{self.url}/storage/v1/object/sign/{self.bucket}/{quote(ruta)}", json={"expiresIn": segundos})
        if r.status_code >= 300:
            return None
        firmado = r.json().get("signedURL") or r.json().get("signedUrl")
        return f"{self.url}/storage/v1{firmado}" if firmado else None


_ALMACEN = None


def obtener_almacen():
    global _ALMACEN
    if _ALMACEN is None:
        _ALMACEN = AlmacenSupabase() if config.supabase_storage_activo() else AlmacenLocal()
    return _ALMACEN


def fijar_almacen(a):
    global _ALMACEN
    _ALMACEN = a
