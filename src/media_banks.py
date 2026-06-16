"""
Bancos de mídia com LICENÇA COMERCIAL apenas.

Pexels, Unsplash, Pixabay (imagem/vídeo) e música royalty-free. Nunca "qualquer
imagem da web". Cada resultado vem com source + license preenchidos.

GARANTIA POR CONSTRUÇÃO (mesmo princípio do _MISSING do gate):
nenhum asset sai daqui sem `license` comercial confirmada. A licença é carimbada por
_finalize_asset a partir da allowlist _COMMERCIAL_LICENSE — NUNCA vem do raw da API.
Se a fonte não está na allowlist, ou o raw não tem path/url, retorna None. Assim
nenhuma implementação de _search_one consegue "inventar" uma licença.

Chaves de API via variáveis de ambiente (nunca hardcoded):
  PEXELS_API_KEY, UNSPLASH_ACCESS_KEY, PIXABAY_API_KEY
"""
import os
import re
from pathlib import Path

ASSETS_DIR = Path(__file__).parent.parent / "output" / "assets"

ALLOWED_IMAGE = {"pexels", "unsplash", "pixabay"}
ALLOWED_VIDEO = {"pexels", "pixabay"}
ALLOWED_MUSIC = {"pixabay_music", "youtube_audio_library"}

# Licença comercial confirmada por fonte. Fonte fora deste mapa = sem licença = None.
_COMMERCIAL_LICENSE = {
    "pexels": "pexels_free_commercial",
    "unsplash": "unsplash_free_commercial",
    "pixabay": "pixabay_content_license",
    "pixabay_music": "pixabay_content_license",
    "youtube_audio_library": "youtube_audio_library_license",
}

_ENV_KEY = {
    "pexels": "PEXELS_API_KEY",
    "unsplash": "UNSPLASH_ACCESS_KEY",
    "pixabay": "PIXABAY_API_KEY",
    "pixabay_music": "PIXABAY_API_KEY",
}

_TIMEOUT = 30


def search_licensed(query: str, cfg: dict, kind: str = "image") -> dict | None:
    """
    Busca um asset licenciado para a query.

    Retorna {"path", "url", "source", "license"} com license comercial garantida,
    OU None se nenhum banco devolver algo com licença comprovada.

    NUNCA retorna asset com license vazia/None/genérica — ver _finalize_asset().
    """
    banks = cfg.get("media_banks", {})
    key = "images" if kind == "image" else kind
    sources = banks.get(key, [])

    for source in sources:
        raw = _search_one(source, query, kind)
        asset = _finalize_asset(raw, source, query)
        if asset is not None:
            return asset
    return None


def _finalize_asset(raw: dict | None, source: str, query: str) -> dict | None:
    """
    Único portão de saída. Só deixa passar asset com licença comercial confirmada.

    A licença vem SEMPRE da allowlist _COMMERCIAL_LICENSE — o campo raw["license"],
    se existir, é ignorado de propósito. Rejeita (None) se: raw vazio, sem path/url,
    ou fonte não mapeada como comercial.
    """
    if not raw:
        return None
    if not raw.get("path") or not raw.get("url"):
        return None

    license_id = _COMMERCIAL_LICENSE.get(source)
    if not license_id:
        return None  # fonte fora da allowlist comercial → descarta

    return {
        "path": raw["path"],
        "url": raw["url"],
        "source": source,
        "license": license_id,   # da allowlist, NUNCA de raw
        "query": query,
    }


def _search_one(source: str, query: str, kind: str) -> dict | None:
    """
    Chamada real por banco. DEVE retornar {"path", "url"} (path = arquivo baixado em
    ASSETS_DIR) ou None. A licença NÃO é decidida aqui — é carimbada em _finalize_asset.
    """
    env_key = _ENV_KEY.get(source)
    if env_key and not os.environ.get(env_key):
        return None  # sem chave configurada → não busca

    try:
        if source == "pexels":
            return _search_pexels(query, kind)
        if source == "unsplash":
            return _search_unsplash(query) if kind == "image" else None
        if source == "pixabay":
            return _search_pixabay(query, kind)
        if source in ("pixabay_music", "youtube_audio_library"):
            # Música não tem download automático por API pública aqui — curadoria manual.
            return None
    except Exception as e:
        print(f"[media_banks] erro em {source}: {e}")
        return None
    return None


def _search_pexels(query: str, kind: str) -> dict | None:
    import requests
    headers = {"Authorization": os.environ["PEXELS_API_KEY"]}
    if kind == "video":
        r = requests.get("https://api.pexels.com/videos/search", headers=headers,
                         params={"query": query, "per_page": 1}, timeout=_TIMEOUT)
        r.raise_for_status()
        vids = r.json().get("videos", [])
        if not vids or not vids[0].get("video_files"):
            return None
        return _download(vids[0]["video_files"][0]["link"], vids[0]["url"], "pexels", query, ".mp4")
    r = requests.get("https://api.pexels.com/v1/search", headers=headers,
                     params={"query": query, "per_page": 1}, timeout=_TIMEOUT)
    r.raise_for_status()
    photos = r.json().get("photos", [])
    if not photos:
        return None
    return _download(photos[0]["src"]["large"], photos[0]["url"], "pexels", query, ".jpg")


def _search_unsplash(query: str) -> dict | None:
    import requests
    r = requests.get("https://api.unsplash.com/search/photos",
                     headers={"Authorization": f"Client-ID {os.environ['UNSPLASH_ACCESS_KEY']}"},
                     params={"query": query, "per_page": 1}, timeout=_TIMEOUT)
    r.raise_for_status()
    results = r.json().get("results", [])
    if not results:
        return None
    return _download(results[0]["urls"]["regular"], results[0]["links"]["html"], "unsplash", query, ".jpg")


def _search_pixabay(query: str, kind: str) -> dict | None:
    import requests
    key = os.environ["PIXABAY_API_KEY"]
    if kind == "video":
        r = requests.get("https://pixabay.com/api/videos/",
                         params={"key": key, "q": query, "per_page": 3}, timeout=_TIMEOUT)
        r.raise_for_status()
        hits = r.json().get("hits", [])
        if not hits:
            return None
        return _download(hits[0]["videos"]["large"]["url"], hits[0]["pageURL"], "pixabay", query, ".mp4")
    r = requests.get("https://pixabay.com/api/",
                     params={"key": key, "q": query, "per_page": 3}, timeout=_TIMEOUT)
    r.raise_for_status()
    hits = r.json().get("hits", [])
    if not hits:
        return None
    return _download(hits[0]["largeImageURL"], hits[0]["pageURL"], "pixabay", query, ".jpg")


def _download(download_url: str, page_url: str, source: str, query: str, ext: str) -> dict | None:
    import requests
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    dest = ASSETS_DIR / f"{source}_{_slug(query)}{ext}"
    r = requests.get(download_url, timeout=_TIMEOUT)
    r.raise_for_status()
    dest.write_bytes(r.content)
    # path + url só. Licença é carimbada em _finalize_asset, não aqui.
    return {"path": str(dest), "url": page_url}


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s[:40] or "asset"
