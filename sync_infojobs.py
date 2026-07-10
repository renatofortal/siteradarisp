# Fetch InfoJobs Brasil telecom-related jobs and POST to RadarISP.
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from pathlib import Path

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
API_ROOT = "https://www.infojobs.com.br"
FRAGMENT = "/mf-publicarea/VacancyList/GetVacancyListFragment"
LISTINGS = [
    "https://www.infojobs.com.br/vagas-de-emprego-telecom.aspx",
    "https://www.infojobs.com.br/vagas-de-emprego-fibra-optica.aspx",
    "https://www.infojobs.com.br/vagas-de-emprego-internet.aspx",
    "https://www.infojobs.com.br/vagas-de-emprego-telecomunicacoes.aspx",
]
MAX_PAGES = int(os.environ.get("INFOJOBS_MAX_PAGES", "20"))
WP_URL = os.environ.get("RADARISP_WP_URL", "https://radarisp.com.br").rstrip("/")
SYNC_KEY = os.environ.get("RADARISP_SYNC_KEY", "")
LOGO_CACHE = Path(__file__).with_name("logo_cache.json")
LOGO_FETCH_LIMIT = int(os.environ.get("INFOJOBS_LOGO_FETCH_LIMIT", "200"))

ALLOW_RE = re.compile(
    r"fibra|telecom|telecomunica|provedor|\bisp\b|ftth|olt|onu|noc|rede[s]?|roteador|switch|"
    r"radioenlace|anten|instalad|field\s*service|call\s*center|sac\b|atendimento|suporte|"
    r"help\s*desk|\bti\b|infra|cloud|devops|\bqa\b|teste|vendas|consultor|comercial|tecnico|"
    r"técnico|analista|engenheir|operador|monitoramento|backbone|\bpop\b|\bcpe\b|internet|"
    r"banda\s*larga|wifi|wi-fi|voip|pabx|datacenter|data\s*center|cftv|alarme|"
    r"seguranca eletronica|segurança eletrônica",
    re.I,
)
DENY_RE = re.compile(
    r"\b(garcom|garçom|cozinheir|bab[aá]|diarista|pedreiro|cabeleireir|manicure|motoboy de comida)\b",
    re.I,
)
COMPANY_HREF_RE = re.compile(
    r'href="(https://www\.infojobs\.com\.br/empresa-[^"]+)"',
    re.I,
)


def fetch(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/json, text/html;q=0.9",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            "Referer": "https://www.infojobs.com.br/",
        },
    )
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read().decode("utf-8", "replace")


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def is_relevant(job: dict) -> bool:
    blob = " ".join(
        [
            str(job.get("title") or ""),
            str(job.get("companyName") or ""),
            str(job.get("department") or ""),
        ]
    )
    if DENY_RE.search(blob):
        return False
    return bool(ALLOW_RE.search(blob))


def workplace_from_card(card: str) -> str:
    if re.search(r"icon-house-and-building", card):
        return "Híbrido"
    if re.search(r"icon-house(?!-and)", card):
        return "Remoto"
    if re.search(r"icon-buildings", card):
        m = re.search(r"icon-buildings[\s\S]{0,220}</svg>\s*([^<]+)", card)
        label = strip_html(m.group(1) if m else "Presencial").lower()
        if "home" in label or "remot" in label:
            return "Remoto"
        if "hibr" in label or "híbr" in label:
            return "Híbrido"
        return "Presencial"
    return ""


def parse_location(raw: str):
    raw = strip_html(raw)
    m = re.match(r"^(.*?)\s*-\s*([A-Za-z]{2})$", raw)
    if m:
        return m.group(1).strip(), m.group(2).upper()
    return raw, ""


def parse_cards(fragment: str):
    parts = re.split(r'(?=<div[^>]*data-id="\d+")', fragment)
    jobs = []
    for card in parts:
        idm = re.search(r'data-id="(\d+)"', card)
        if not idm:
            continue
        job_id = int(idm.group(1))
        hm = re.search(r'data-href="(/vaga[^"]+)"', card)
        tm = re.search(r"js_vacancyTitle[^>]*>\s*(.*?)\s*</h2>", card, re.S)
        if not hm or not tm:
            continue
        title = strip_html(tm.group(1))
        if not title:
            continue
        company = "Empresa Confidencial"
        company_url = ""
        cm = re.search(
            r'href="(https://www\.infojobs\.com\.br/empresa-[^"]+)"[^>]*>\s*(.*?)\s*</a>',
            card,
            re.S,
        )
        if cm:
            company_url = cm.group(1)
            cand = re.sub(r"Este selo indica.*$", "", strip_html(cm.group(2))).strip()
            if cand:
                company = cand
        city, state = "", ""
        lm = re.search(r'<div class="mb-8">\s*([^<]+?)\s*<span hidden', card)
        if not lm:
            lm = re.search(r'<div class="mb-8">\s*([^<]+?)\s*</div>', card)
        if lm:
            city, state = parse_location(lm.group(1))
        posted = ""
        pm = re.search(r'class="js_date" data-value="([^"]+)"', card)
        if pm:
            posted = pm.group(1).strip()
        jobs.append(
            {
                "id": job_id,
                "title": title,
                "companyName": company,
                "companyUrl": company_url,
                "city": city,
                "state": state,
                "workplaceLabel": workplace_from_card(card),
                "department": "",
                "type": "",
                "applyUrl": API_ROOT + hm.group(1),
                "postedAt": posted,
            }
        )
    return jobs


def fetch_listing(listing: str):
    all_jobs = []
    empty = 0
    for page in range(1, MAX_PAGES + 1):
        url = re.sub(r"[?&]page=\d+", "", listing).rstrip("?&")
        url += ("&" if "?" in url else "?") + f"page={page}"
        api = API_ROOT + FRAGMENT + "?url=" + urllib.parse.quote(url, safe="")
        try:
            data = json.loads(fetch(api))
        except Exception as e:
            print("ERR", listing, page, e)
            break
        jobs = parse_cards(data.get("listFragmentHTML") or "")
        print(listing.split("/")[-1], "page", page, "jobs", len(jobs), "eof", data.get("eof"))
        if not jobs:
            empty += 1
        else:
            empty = 0
            all_jobs.extend(jobs)
        if data.get("eof") or empty >= 2:
            break
        time.sleep(0.3)
    return all_jobs


def load_logo_cache():
    if LOGO_CACHE.exists():
        try:
            return json.loads(LOGO_CACHE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_logo_cache(cache: dict):
    LOGO_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def is_valid_logo(url: str) -> bool:
    if not url or not url.startswith("http"):
        return False
    u = url.lower()
    bad = (
        "placeholder",
        "og-image.png",
        "logo-duotone",
        "none.gif",
        "/mail/images/",
        "favicon",
        "mf-publicarea/images/common/",
        "app_theme/images/logo",
        "awards-footer",
    )
    if any(b in u for b in bad):
        return False
    # Prefer InfoJobs CDN company logos; reject other generic InfoJobs assets.
    if "infojobs.com.br" in u and "/logos/" not in u:
        return False
    return True


def extract_logo_from_html(html: str) -> str:
    patterns = [
        r'property="og:image:secure_url"\s+content="([^"]+)"',
        r'content="([^"]+)"\s+property="og:image:secure_url"',
        r'property="og:image"\s+content="([^"]+)"',
        r'content="([^"]+)"\s+property="og:image"',
        r'<meta[^>]+name="twitter:image"[^>]+content="([^"]+)"',
        r'<img[^>]+alt="[^"]*logo[^"]*"[^>]+src="([^"]+)"',
        r'<img[^>]+src="(https://ncdn\d*\.infojobs\.com\.br/logos/[^"]+)"',
        r'<img[^>]+src="(https://[^"]+/logos/[^"]+)"',
    ]
    for pat in patterns:
        for m in re.finditer(pat, html, re.I):
            url = m.group(1).strip()
            if url.startswith("//"):
                url = "https:" + url
            # Prefer full logo over tiny _t thumbnails when both exist.
            url = re.sub(r"(_t)(\.(?:jpg|jpeg|png|webp))(?:\?.*)?$", r"\2", url, flags=re.I)
            if is_valid_logo(url):
                return url
    return ""


def company_url_from_html(html: str) -> str:
    m = COMPANY_HREF_RE.search(html or "")
    return m.group(1) if m else ""


def enrich_logos(jobs: list):
    cache = load_logo_cache()
    fetched = 0
    applied = 0
    for job in jobs:
        company = (job.get("companyName") or "").strip()
        if not company or company.lower() == "empresa confidencial":
            continue
        key = company.lower()
        if key in cache:
            if cache[key]:
                job["logo"] = cache[key]
                applied += 1
            continue
        if fetched >= LOGO_FETCH_LIMIT:
            continue

        company_url = (job.get("companyUrl") or "").strip()
        try:
            if not company_url:
                apply_url = job.get("applyUrl") or ""
                if not apply_url:
                    cache[key] = ""
                    continue
                vac_html = fetch(apply_url)
                fetched += 1
                company_url = company_url_from_html(vac_html)
                time.sleep(0.2)
                if not company_url:
                    cache[key] = ""
                    continue

            html = fetch(company_url)
            fetched += 1
            logo = extract_logo_from_html(html)
            if logo:
                cache[key] = logo
                job["logo"] = logo
                applied += 1
                print("logo", company, logo[:100])
            else:
                cache[key] = ""
                print("logo miss", company, company_url)
            time.sleep(0.25)
        except Exception as e:
            print("logo err", company, e)
            fetched += 1
            # Don't poison cache on transient errors.
    save_logo_cache(cache)
    print(
        "logos fetched this run",
        fetched,
        "applied",
        applied,
        "cache size",
        len(cache),
        "with logo",
        sum(1 for v in cache.values() if v),
    )


def post_to_wordpress(jobs):
    if not SYNC_KEY:
        raise SystemExit("RADARISP_SYNC_KEY missing")
    payload = json.dumps({"source": "infojobs", "count": len(jobs), "jobs": jobs}, ensure_ascii=False).encode("utf-8")
    url = WP_URL + "/wp-json/radarisp/v1/infojobs-import"
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-RadarISP-Sync-Key": SYNC_KEY,
            "User-Agent": "RadarISP-InfoJobs-Sync/1.2",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            body = r.read().decode("utf-8", "replace")
            print("WP", r.status, body[:500])
            return json.loads(body)
    except urllib.error.HTTPError as e:
        print("WP ERROR", e.code, e.read().decode("utf-8", "replace")[:800])
        raise


def main():
    seen = {}
    for listing in LISTINGS:
        for job in fetch_listing(listing):
            seen[job["id"]] = job
    jobs = list(seen.values())
    print("unique jobs", len(jobs))
    filtered = [j for j in jobs if is_relevant(j)]
    print("after quality filter", len(filtered), "dropped", len(jobs) - len(filtered))
    enrich_logos(filtered)
    result = post_to_wordpress(filtered)
    print("done", result)


if __name__ == "__main__":
    main()
