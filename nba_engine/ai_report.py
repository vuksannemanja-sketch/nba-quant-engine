"""AI izvještaj: Claude bira najsigurnije opklade iz dnevne analize i obrazlaže ih.

Tok:
  1. iz snimljene analize (``history/analysis_*.csv``) pravi se sažeta tabela kandidata + lista povreda
  2. jedan poziv Claude API-ja (strukturisan JSON odgovor) vraća N izbora sa obrazloženjem
  3. izbori se provjere (igrač mora biti u ponudi, bez duplikata) i snime:
       history/ai/analysis_<datum>_<vrijeme>[_daily].csv   isti format kao analiza → poravnava ga isti settle
       history/ai/report_<datum>_<vrijeme>[_daily].json    izvještaj za prikaz (sažetak, obrazloženja, tokeni)

AI izbori imaju vlastiti ledger (``history/ai/ledger.csv``), pa se ocjenjuju odvojeno od modela. I ovdje važi
pravilo „jedna zvanična analiza po danu“: izvještaj iz dnevnog posla nosi oznaku ``daily``.

Ključ: ``ANTHROPIC_API_KEY`` u ``.env``; model: ``ANTHROPIC_MODEL`` (podrazumijevano claude-opus-5-5).
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from .config import Settings
from .history import DAILY_TAG, analysis_tag, list_history, save_analysis, timestamp_now
from .utils import normalize_name

Logger = Callable[[str], None]

AI_PICKS = 10                 # koliko izbora AI daje dnevno
MAX_PER_GAME = 3              # najviše izbora iz istog meča
AI_EFFORT = "high"            # koliko temeljno model razmišlja (low | medium | high | xhigh | max)
AI_MAX_TOKENS = 64000         # gornja granica odgovora (razmišljanje + izvještaj); plaća se samo potrošeno
FALLBACK_BETA = "server-side-fallback-2026-07-01"
REPORT_PREFIX = "report_"
_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})")
_TS_FMT = "%Y-%m-%d_%H-%M-%S"

# Cijene po milionu tokena (ulaz, izlaz) u USD — stanje 10/2026. Služe samo za okvirni prikaz troška;
# stvarni račun je na console.anthropic.com.
MODEL_PRICES: Dict[str, Tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}

# (kolona u analizi, kratko ime u tabeli koju vidi AI)
CANDIDATE_COLUMNS: List[Tuple[str, str]] = [
    ("Player", "player"), ("TEAM_ABBR", "team"), ("OPP_TEAM", "opp"), ("Is Home", "home"),
    ("Line", "line"), ("Over Odds", "over_odds"), ("Under Odds", "under_odds"),
    ("Final Projection", "proj"), ("Calibrated Projection", "proj_cal"), ("Sigma", "sigma"),
    ("P(Over)%", "p_over"), ("P(Under)%", "p_under"), ("Market P(Over)%", "mkt_p_over"),
    ("Model Pick", "model_pick"), ("Best EV %", "ev_pct"), ("True Score", "score"),
    ("Minutes", "min"), ("L10 MIN", "l10_min"), ("SeasonAnchor", "season_pts"),
    ("L10 PTS", "l10_pts"), ("L5 PTS", "l5_pts"), ("L10 STD", "l10_std"), ("L10 Trend", "l10_trend"),
    ("H2H PTS Avg", "h2h_avg"), ("H2H Games", "h2h_games"), ("Usage %", "usg"), ("Prior Weight", "prior_w"),
    ("B2B Team", "b2b"), ("B2B Opp", "opp_b2b"), ("Rest Days", "rest"),
    ("Injury Boost", "inj_boost"), ("Injured Usage Lost", "team_usg_out"), ("Direct Player Penalty", "inj_penalty"),
    ("DEF Factor", "def_factor"), ("TOTAL_MATCH_USED", "game_total"),
]
_BOOL_COLUMNS = ("home", "b2b", "opp_b2b")

COLUMN_LEGEND = """\
player, team, opp — igrač, njegov tim, protivnik; home: 1 = igra kod kuće, 0 = gostuje
line — linija poena; over_odds / under_odds — decimalne kvote za više / manje
proj — projekcija poena našeg modela; proj_cal — ista projekcija poslije kalibracije prema tržištu
sigma — procijenjeno rasipanje poena igrača (standardna devijacija)
p_over / p_under — vjerovatnoća modela u % (Monte Carlo); mkt_p_over — vjerovatnoća koju podrazumijevaju kvote, bez marže
model_pick — strana koju je izabrao model (NO VALUE = model ne vidi vrijednost); ev_pct — očekivana vrijednost u %
score — zbirni rang modela (veći = bolji)
min — projektovane minute; l10_min — prosjek minuta u zadnjih 10 utakmica
season_pts — sezonski nivo poena sveden na projektovane minute
l10_pts / l5_pts — prosjek poena u zadnjih 10 / 5 utakmica; l10_std — rasipanje poena u zadnjih 10; l10_trend — nagib trenda (poeni po utakmici)
h2h_avg / h2h_games — prosjek poena protiv ovog protivnika i broj tih utakmica (h2h_avg vrijedi samo kad je h2h_games veći od 0)
usg — udio napada koji igrač završava (usage %)
prior_w — udio prošle sezone u sezonskim brojkama (veći broj = manje ovosezonskih utakmica, manje pouzdano)
b2b / opp_b2b — 1 = tim / protivnik igra drugi dan zaredom; rest — dani odmora tima
inj_boost — faktor zbog izostanka saigrača (veći od 1 = više šuteva za ovog igrača); team_usg_out — usage % saigrača koji ne igraju
inj_penalty — faktor zbog igračeve vlastite povrede (manji od 1 = umanjeno)
def_factor — faktor odbrane protivnika (veći od 1 = lakši protivnik)
game_total — očekivani zbir poena meča po kladionici
status — status igrača na listi povreda (prazno = nije na listi)"""

REPORT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "3 do 5 rečenica o današnjoj ponudi, na srpskom (ijekavica)."},
        "picks": {
            "type": "array",
            "description": "Izbori poredani od najsigurnijeg.",
            "items": {
                "type": "object",
                "properties": {
                    "player": {"type": "string", "description": "Ime igrača tačno kao u koloni player."},
                    "side": {"type": "string", "enum": ["OVER", "UNDER"]},
                    "confidence": {"type": "integer", "description": "Procjena vjerovatnoće prolaza u procentima."},
                    "reason": {"type": "string", "description": "2 do 3 rečenice sa konkretnim brojkama."},
                    "risk": {"type": "string", "description": "Jedna rečenica: šta može pokvariti opkladu."},
                },
                "required": ["player", "side", "confidence", "reason", "risk"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "picks"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
Ti si iskusan analitičar NBA opklada na poene igrača (tržište „player points over/under“). Radiš za jednog korisnika \
koji svaki dan prati dnevnu ponudu kroz vlastiti statistički model. Tvoj zadatak je da iz današnje ponude izabereš \
{n} NAJSIGURNIJIH opklada i napišeš kratak izvještaj koji on čita prije uplate. Tvoji izbori se svaki dan \
upoređuju sa stvarnim rezultatima i ocjenjuju odvojeno od modela, pa je tačnost jedino mjerilo.

Šta znači „najsigurnija“: opklada sa najvećom vjerovatnoćom da prođe. Ne tražiš najveću kvotu ni najveći očekivani \
profit, nego izbore kod kojih se najviše nezavisnih pokazatelja slaže i kod kojih najmanje toga može poći po zlu.

Na šta da paziš (ovo su smjernice, presudi sam prema podacima):
- Uloga i minute. Stabilne minute i stalna uloga vrijede više od visoke projekcije.
- Razmak između projekcije i linije u odnosu na rasipanje (sigma, l10_std). Mali razmak uz veliko rasipanje nije siguran izbor.
- Slaganje izvora: sezonski nivo, zadnjih 10 i zadnjih 5 utakmica, projekcija modela i linija kladionice.
- Povrede. Igrača sa statusom OUT ili DOUBTFUL ne biraj, jer se takva opklada poništava. QUESTIONABLE i DAY-TO-DAY su \
rizik za minute. Izostanci saigrača mijenjaju raspodjelu šuteva, pročitaj i opise povreda.
- Raspored: drugi dan zaredom, dani odmora, gostovanje.
- Rana sezona: kad je prior_w visok, ovosezonski uzorak je mali i brojke su manje pouzdane.
- Model nije nepogrešiv. Njegove vjerovatnoće (p_over, p_under) su procjene. Vrlo velik razmak između projekcije i \
linije češće znači da model nešto ne vidi (ulogu, minute, povredu) nego da je kladionica pogriješila. Smiješ izabrati \
stranu suprotnu od modela ako podaci to opravdavaju.

Podaci u poruci su svježi i povučeni danas. Oslanjaj se na njih, a ne na sjećanje o sastavima, trejdovima ili \
povredama, jer se to mijenja iz dana u dan. Ne izmišljaj podatke kojih nema u poruci.

Pravila izbora:
- Tačno {n} izbora, svaki za drugog igrača, poredani od najsigurnijeg.
- Ime igrača prepiši tačno kako piše u koloni player.
- Najviše {max_per_game} izbora iz istog meča, da jedan loš meč ne obori cijeli dan.
- confidence je tvoja iskrena procjena vjerovatnoće prolaza u procentima (cijeli broj). Kod kvota oko 1.90 \
procjene iznad 65 su rijetko opravdane.

Izvještaj piši na srpskom jeziku, ijekavicom i latinicom, jednostavnim rječnikom:
- summary: 3 do 5 rečenica o današnjoj ponudi: kakav je dan, šta je glavni rizik i šta korisnik treba da provjeri prije uplate.
- reason: 2 do 3 rečenice sa konkretnim brojkama iz tabele koje opravdavaju izbor.
- risk: jedna rečenica o tome šta može pokvariti opkladu."""


class AiReportError(RuntimeError):
    """Greška AI izvještaja; poruka je već napisana za korisnika."""


@dataclass
class AiReport:
    data: Dict[str, Any]
    report_path: Path
    analysis_path: Path


# ---------------------------------------------------------------------------
# Ulaz za model: tabela kandidata, povrede, dosadašnji učinak
# ---------------------------------------------------------------------------

def _truthy(v: Any) -> bool:
    return str(v).strip().lower() in ("true", "1", "1.0")


def build_candidates(df: pd.DataFrame, injuries: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Sažeta tabela koju vidi AI: jedan red po igraču iz ponude, kratka imena kolona, status povrede."""
    keys = df["Player"].astype(str).map(normalize_name)
    base = df.loc[~keys.duplicated()].reset_index(drop=True)
    out = pd.DataFrame({short: base[src] for src, short in CANDIDATE_COLUMNS if src in base.columns})
    for col in _BOOL_COLUMNS:
        if col in out.columns:
            out[col] = [("" if pd.isna(v) else int(_truthy(v))) for v in out[col]]
    status: Dict[str, str] = {}
    if injuries is not None and not injuries.empty and {"PLAYER", "STATUS"} <= set(injuries.columns):
        for name, st in zip(injuries["PLAYER"], injuries["STATUS"]):
            if pd.notna(name) and pd.notna(st):
                status.setdefault(normalize_name(str(name)), str(st).strip().upper())
    out["status"] = [status.get(normalize_name(str(p)), "") for p in out["player"]]
    return out


def candidates_csv(cands: pd.DataFrame) -> str:
    return cands.to_csv(index=False, float_format="%g").strip()


def injury_lines(injuries: Optional[pd.DataFrame], teams, max_desc: int = 160) -> str:
    """Povrede timova iz ponude: ``TIM | igrač | STATUS | opis`` (opis skraćen)."""
    if injuries is None or injuries.empty or not {"PLAYER", "TEAM_ABBR", "STATUS"} <= set(injuries.columns):
        return ""
    wanted = {str(t).upper() for t in teams if pd.notna(t) and str(t).strip()}
    inj = injuries[injuries["TEAM_ABBR"].astype(str).str.upper().isin(wanted)].copy()
    if inj.empty:
        return ""
    inj = inj.sort_values(["TEAM_ABBR", "STATUS", "PLAYER"])
    lines = []
    for _, r in inj.iterrows():
        desc = str(r.get("DESCRIPTION", "") or "").strip()
        desc = "" if desc.lower() == "nan" else " ".join(desc.split())
        if len(desc) > max_desc:
            desc = desc[:max_desc].rstrip() + "…"
        lines.append(f"{str(r['TEAM_ABBR']).upper()} | {r['PLAYER']} | {str(r['STATUS']).upper()}" + (f" | {desc}" if desc else ""))
    return "\n".join(lines)


def model_track_record(history_dir) -> str:
    """Jedna rečenica o dosadašnjem učinku modela po strani (OVER/UNDER) — kontekst za AI. Prazno ako nema podataka."""
    from .settle import load_all_settled
    try:
        settled = load_all_settled(history_dir)
    except Exception:  # noqa: BLE001 — oštećen fajl ne smije zaustaviti izvještaj
        return ""
    if settled.empty or not {"Bet Result", "Model Pick"} <= set(settled.columns):
        return ""
    parts = []
    for side in ("OVER", "UNDER"):
        res = settled.loc[settled["Model Pick"] == side, "Bet Result"].astype(str)
        wins, losses = int((res == "WIN").sum()), int((res == "LOSS").sum())
        if wins + losses:
            parts.append(f"{side} {wins} od {wins + losses} ({wins / (wins + losses) * 100:.0f} %)")
    if not parts:
        return ""
    days = int(settled["Analysis"].nunique()) if "Analysis" in settled.columns else 0
    return (f"Dosadašnji učinak modela na svim njegovim pickovima ({days} dana poravnato): pogođeno "
            + ", ".join(parts) + ".")


def build_prompt(cands: pd.DataFrame, n: int, game_date: _dt.date, season: str, injuries_text: str = "",
                 track_record: str = "") -> Tuple[str, str]:
    """(sistemska poruka, korisnička poruka sa podacima)."""
    system = SYSTEM_PROMPT.format(n=n, max_per_game=MAX_PER_GAME)
    parts = [f"Datum mečeva (američki dan): {game_date.strftime('%d.%m.%Y')}. Sezona: {season}. "
             f"Igrača u ponudi: {len(cands)}."]
    if track_record:
        parts.append(track_record)
    parts.append("OBJAŠNJENJE KOLONA\n" + COLUMN_LEGEND)
    parts.append("PONUDA I PROJEKCIJE (CSV, poredano po rangu modela)\n" + candidates_csv(cands))
    parts.append("POVREDE U TIMOVIMA IZ PONUDE (tim | igrač | status | opis)\n"
                 + (injuries_text or "Lista povreda nije dostupna."))
    parts.append(f"Izaberi {n} najsigurnijih opklada i napiši izvještaj.")
    return system, "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Poziv Claude API-ja
# ---------------------------------------------------------------------------

def make_client(settings: Settings):
    if not settings.anthropic_api_key:
        raise AiReportError("ANTHROPIC_API_KEY nije postavljen u .env — AI izvještaj ne može da se napravi.")
    try:
        import anthropic
    except ImportError as e:
        raise AiReportError("Paket `anthropic` nije instaliran. Pokreni: pip install -r requirements.txt") from e
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def call_model(client, model: str, system: str, user: str, log: Optional[Logger] = None):
    """Jedan zahtjev sa strukturisanim JSON odgovorom; vraća gotovu poruku (streaming, da duži odgovor ne istekne)."""
    import anthropic

    request = dict(
        model=model,
        max_tokens=AI_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": AI_EFFORT, "format": {"type": "json_schema", "schema": REPORT_SCHEMA}},
    )
    try:
        # Ako sigurnosni filter odbije zahtjev, Anthropic ga sam ponovi na rezervnom modelu (beta opcija).
        with client.beta.messages.stream(**request, betas=[FALLBACK_BETA], fallbacks="default") as stream:
            return stream.get_final_message()
    except anthropic.BadRequestError as e:
        if log:
            log(f"ℹ️  Zahtjev sa rezervnim modelom nije prihvaćen ({getattr(e, 'message', e)}); ponavljam bez te opcije.")
        with client.messages.stream(**request) as stream:
            return stream.get_final_message()


def friendly_error(e: Exception, model: str) -> str:
    """Greška Claude API-ja prevedena u poruku za korisnika."""
    try:
        import anthropic
    except ImportError:
        return str(e)
    msg = str(getattr(e, "message", "") or e)
    if isinstance(e, anthropic.AuthenticationError):
        return "Anthropic ključ nije ispravan — provjeri ANTHROPIC_API_KEY u .env."
    if isinstance(e, anthropic.PermissionDeniedError):
        return f"Ključ nema dozvolu za model {model}."
    if isinstance(e, anthropic.NotFoundError):
        return f"Model „{model}“ ne postoji — provjeri ANTHROPIC_MODEL u .env."
    if isinstance(e, anthropic.RateLimitError):
        return "Anthropic je privremeno ograničio broj zahtjeva — pokušaj ponovo za nekoliko minuta."
    if isinstance(e, anthropic.BadRequestError):
        if "credit balance" in msg.lower():
            return "Na Anthropic nalogu nema kredita — dopuni ga na console.anthropic.com (Billing)."
        return f"Anthropic nije prihvatio zahtjev: {msg[:300]}"
    if isinstance(e, anthropic.APIStatusError):
        return f"Greška na Anthropic serveru ({getattr(e, 'status_code', '?')}) — pokušaj kasnije."
    if isinstance(e, anthropic.APIConnectionError):
        return "Nema veze sa Anthropic serverom — provjeri internet."
    return f"AI izvještaj nije uspio: {msg[:300] or e.__class__.__name__}"


def parse_response(message) -> Dict[str, Any]:
    """Provjeri razlog završetka i vrati JSON iz odgovora."""
    stop = getattr(message, "stop_reason", None)
    if stop == "refusal":
        raise AiReportError("Claude je odbio da odgovori na ovaj zahtjev (sigurnosni filter).")
    if stop == "max_tokens":
        raise AiReportError("Odgovor je prekinut prije kraja (dostignuta gornja granica dužine).")
    text = next((b.text for b in (getattr(message, "content", None) or []) if getattr(b, "type", "") == "text"), None)
    if not text:
        raise AiReportError("Claude nije vratio tekst odgovora.")
    try:
        data = json.loads(text)
    except ValueError as e:
        raise AiReportError(f"Odgovor nije ispravan JSON: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("picks"), list):
        raise AiReportError("Odgovor nema listu izbora (picks).")
    return data


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> Optional[float]:
    """Okvirni trošak poziva u USD (None za model bez poznate cijene)."""
    for name in sorted(MODEL_PRICES, key=len, reverse=True):
        if str(model or "").startswith(name):
            price_in, price_out = MODEL_PRICES[name]
            return round(input_tokens / 1e6 * price_in + output_tokens / 1e6 * price_out, 4)
    return None


# ---------------------------------------------------------------------------
# Provjera izbora i snimanje
# ---------------------------------------------------------------------------

def _as_int(v: Any) -> Optional[int]:
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def _as_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else round(f, 2)


def _as_text(v: Any) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def select_picks(raw_picks: List[Dict[str, Any]], df: pd.DataFrame, n: int) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Zadrži samo ispravne izbore: igrač iz ponude, bez duplikata, strana OVER/UNDER, najviše ``n``."""
    keys = df["Player"].astype(str).map(normalize_name).tolist()
    row_of: Dict[str, int] = {}
    for i, k in enumerate(keys):
        row_of.setdefault(k, i)
    chosen: List[Dict[str, Any]] = []
    warnings: List[str] = []
    seen = set()
    for item in raw_picks:
        if not isinstance(item, dict):
            continue
        name, side = _as_text(item.get("player")), _as_text(item.get("side")).upper()
        key = normalize_name(name)
        if key not in row_of:
            warnings.append(f"„{name}“ nije u ponudi — izbor odbačen")
            continue
        if key in seen:
            warnings.append(f"„{name}“ je naveden dva puta — zadržan prvi")
            continue
        if side not in ("OVER", "UNDER"):
            warnings.append(f"„{name}“: nepoznata strana „{side}“ — izbor odbačen")
            continue
        seen.add(key)
        chosen.append({"row": row_of[key], "side": side, "confidence": _as_int(item.get("confidence")),
                       "reason": _as_text(item.get("reason")), "risk": _as_text(item.get("risk"))})
        if len(chosen) == n:
            break
    return chosen, warnings


def build_ai_analysis(df: pd.DataFrame, chosen: List[Dict[str, Any]]) -> pd.DataFrame:
    """Redovi analize za izabrane igrače u formatu koji razumije settle: ``Model Pick`` = strana koju je izabrao AI."""
    base = df.reset_index(drop=True)
    rows = base.iloc[[c["row"] for c in chosen]].copy().reset_index(drop=True)
    sides = [c["side"] for c in chosen]
    rows["Engine Pick"] = rows["Model Pick"] if "Model Pick" in rows.columns else ""
    rows["Model Pick"] = sides
    if {"P(Over)%", "P(Under)%"} <= set(rows.columns):
        rows["Pick Confidence %"] = [rows.loc[i, "P(Over)%"] if s == "OVER" else rows.loc[i, "P(Under)%"]
                                     for i, s in enumerate(sides)]
    rows.insert(0, "AI Rank", range(1, len(rows) + 1))
    rows["AI Confidence %"] = [c["confidence"] for c in chosen]
    rows["AI Reason"] = [c["reason"] for c in chosen]
    rows["AI Risk"] = [c["risk"] for c in chosen]
    return rows


def _pick_entries(frame: pd.DataFrame) -> List[Dict[str, Any]]:
    out = []
    for _, r in frame.iterrows():
        side = r["Model Pick"]
        out.append({
            "rank": int(r["AI Rank"]), "player": _as_text(r.get("Player")), "team": _as_text(r.get("TEAM_ABBR")),
            "opp": _as_text(r.get("OPP_TEAM")), "home": _truthy(r.get("Is Home")), "side": side,
            "line": _as_float(r.get("Line")),
            "odds": _as_float(r.get("Over Odds") if side == "OVER" else r.get("Under Odds")),
            "projection": _as_float(r.get("Final Projection")), "model_prob": _as_float(r.get("Pick Confidence %")),
            "engine_pick": _as_text(r.get("Engine Pick")), "confidence": _as_int(r.get("AI Confidence %")),
            "reason": _as_text(r.get("AI Reason")), "risk": _as_text(r.get("AI Risk")),
        })
    return out


def game_date_for_timestamp(ts: str) -> _dt.date:
    """Američki datum mečeva za vremensku oznaku fajla (isto pravilo kao u settle)."""
    from .settle import US_DAY_CUTOFF_HOUR
    when = _dt.datetime.strptime(ts, _TS_FMT)
    return (when - _dt.timedelta(days=1)).date() if when.hour < US_DAY_CUTOFF_HOUR else when.date()


def current_game_date(now: Optional[_dt.datetime] = None) -> _dt.date:
    return game_date_for_timestamp((now or _dt.datetime.now()).strftime(_TS_FMT))


def _free_timestamp(ai_dir: Path, ts: str, suffix: str) -> str:
    """Ako fajlovi sa ovom oznakom već postoje, pomjeri je sekundu po sekundu (ništa se ne piše preko starog)."""
    when = _dt.datetime.strptime(ts, _TS_FMT)
    while ((ai_dir / f"analysis_{when.strftime(_TS_FMT)}{suffix}.csv").exists()
           or (ai_dir / f"{REPORT_PREFIX}{when.strftime(_TS_FMT)}{suffix}.json").exists()):
        when += _dt.timedelta(seconds=1)
    return when.strftime(_TS_FMT)


def generate_ai_report(df: pd.DataFrame, settings: Settings, client=None, injuries: Optional[pd.DataFrame] = None,
                       source_name: str = "", timestamp: Optional[str] = None, tag: Optional[str] = None,
                       n: int = AI_PICKS, log: Optional[Logger] = None, track_record: str = "") -> AiReport:
    """Napravi AI izvještaj za jednu analizu i snimi ga u ``history/ai/``. Baca AiReportError sa porukom za korisnika."""
    if df is None or df.empty or "Player" not in df.columns:
        raise AiReportError("Analiza je prazna — nema iz čega da se bira.")
    df = df.reset_index(drop=True)
    cands = build_candidates(df, injuries)
    n = min(int(n), len(cands))
    ts = timestamp or timestamp_now()
    game_date = game_date_for_timestamp(ts)
    system, user = build_prompt(cands, n, game_date, settings.season,
                                injury_lines(injuries, cands.get("team", pd.Series(dtype=str)).tolist()
                                             + cands.get("opp", pd.Series(dtype=str)).tolist()),
                                track_record)
    client = client or make_client(settings)
    try:
        message = call_model(client, settings.ai_model, system, user, log=log)
    except AiReportError:
        raise
    except Exception as e:  # noqa: BLE001 — sve greške API-ja se prevode u poruku za korisnika
        raise AiReportError(friendly_error(e, settings.ai_model)) from e
    raw = parse_response(message)
    chosen, warnings = select_picks(raw["picks"], df, n)
    if not chosen:
        raise AiReportError("Nijedan AI izbor nije prošao provjeru (imena se ne poklapaju sa ponudom).")
    if len(chosen) < n:
        warnings.append(f"AI je dao {len(chosen)} ispravnih izbora umjesto {n}")
    frame = build_ai_analysis(df, chosen)

    ai_dir = settings.ai_history_dir
    ai_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"_{tag}" if tag else ""
    ts = _free_timestamp(ai_dir, ts, suffix)
    analysis_path = save_analysis(frame, ai_dir, ts, tag=tag)
    usage = getattr(message, "usage", None)
    tokens_in, tokens_out = int(getattr(usage, "input_tokens", 0) or 0), int(getattr(usage, "output_tokens", 0) or 0)
    served_by = str(getattr(message, "model", "") or settings.ai_model)
    report_path = ai_dir / f"{REPORT_PREFIX}{ts}{suffix}.json"
    data: Dict[str, Any] = {
        "file": report_path.name, "analysis_file": analysis_path.name, "source_analysis": source_name,
        "created": _dt.datetime.now().isoformat(timespec="seconds"), "game_date": game_date.isoformat(),
        "official": tag == DAILY_TAG, "season": settings.season,
        "model": served_by, "requested_model": settings.ai_model,
        "candidates": int(len(cands)), "summary": _as_text(raw.get("summary")), "picks": _pick_entries(frame),
        "warnings": warnings,
        "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out,
                  "cost_usd": estimate_cost(served_by, tokens_in, tokens_out)},
    }
    report_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return AiReport(data=data, report_path=report_path, analysis_path=analysis_path)


# ---------------------------------------------------------------------------
# Čitanje snimljenih izvještaja
# ---------------------------------------------------------------------------

def list_reports(ai_dir) -> List[Path]:
    ai_dir = Path(ai_dir)
    return sorted(ai_dir.glob(f"{REPORT_PREFIX}*.json")) if ai_dir.is_dir() else []


def load_report(path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def all_reports(ai_dir) -> List[Dict[str, Any]]:
    return [r for r in (load_report(p) for p in list_reports(ai_dir)) if r]


def latest_report(ai_dir) -> Optional[Dict[str, Any]]:
    """Izvještaj za najnoviji dan mečeva; ako ih tog dana ima više — zvanični (dnevni posao), pa najnoviji."""
    reports = all_reports(ai_dir)
    if not reports:
        return None
    return max(reports, key=lambda r: (str(r.get("game_date", "")), bool(r.get("official")), str(r.get("created", "")),
                                       str(r.get("file", ""))))


def report_for_source(ai_dir, source_name: str) -> Optional[Dict[str, Any]]:
    """Već napravljen izvještaj za dati fajl analize (da se isti poziv ne plaća dva puta)."""
    for rep in reversed(all_reports(ai_dir)):
        if source_name and rep.get("source_analysis") == source_name:
            return rep
    return None


def cost_summary(ai_dir, month: Optional[str] = None) -> Dict[str, Any]:
    """Broj izvještaja i okvirni trošak (USD), opciono samo za mjesec ``YYYY-MM`` (po datumu mečeva)."""
    reports = [r for r in all_reports(ai_dir) if month is None or str(r.get("game_date", "")).startswith(month)]
    costs = [(r.get("usage") or {}).get("cost_usd") for r in reports]
    known = [float(c) for c in costs if c is not None]
    return {"reports": len(reports), "cost_usd": round(sum(known), 2), "unknown": len(costs) - len(known)}


def picks_table(report: Dict[str, Any]) -> pd.DataFrame:
    rows = [{"#": p.get("rank"), "Igrač": p.get("player"), "Meč": f"{p.get('team', '')}–{p.get('opp', '')}",
             "Izbor": f"{p.get('side', '')} {p.get('line', '')}", "Kvota": p.get("odds"),
             "AI %": p.get("confidence"), "Model %": p.get("model_prob"), "Model kaže": p.get("engine_pick")}
            for p in report.get("picks", [])]
    return pd.DataFrame(rows)


def _fmt_day(iso: str) -> str:
    try:
        return _dt.date.fromisoformat(str(iso)[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return str(iso)


def render_markdown(report: Dict[str, Any]) -> str:
    """Izvještaj kao Markdown (bočna traka aplikacije i ispis u terminalu)."""
    created = str(report.get("created", ""))[:16].replace("T", " ")
    lines = [f"**Mečevi {_fmt_day(report.get('game_date', ''))}** · napravljeno {created} · {report.get('model', '')}", ""]
    if report.get("summary"):
        lines += [str(report["summary"]), ""]
    for p in report.get("picks", []):
        where = "kod kuće" if p.get("home") else "u gostima"
        conf = f" · sigurnost {p['confidence']} %" if p.get("confidence") is not None else ""
        odds = f" @ {p['odds']}" if p.get("odds") is not None else ""
        # dva razmaka na kraju reda = prelom reda u Markdownu; prazni redovi razdvajaju obrazloženje i rizik
        lines.append(f"**{p.get('rank')}. {p.get('player')}** — **{p.get('side')} {p.get('line')}**{odds}  ")
        lines += [f"{p.get('team')}–{p.get('opp')}, {where}{conf}", ""]
        if p.get("reason"):
            lines += [str(p["reason"]), ""]
        if p.get("risk"):
            lines += [f"⚠️ {p['risk']}", ""]
    for w in report.get("warnings", []):
        lines.append(f"ℹ️ {w}")
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Izvještaj za današnju zvaničnu analizu (dnevni posao i komandna linija)
# ---------------------------------------------------------------------------

def official_analysis_for(history_dir, game_date: _dt.date) -> Optional[Path]:
    from .settle import official_analyses
    return official_analyses(list_history(history_dir)).get(game_date)


def _load_injuries(settings: Settings) -> Optional[pd.DataFrame]:
    try:
        from .loaders import load_bundle
        return load_bundle(settings).injuries
    except Exception:  # noqa: BLE001 — bez liste povreda izvještaj se i dalje može napraviti
        return None


def run_for_today(settings: Settings, log: Optional[Logger] = None, force: bool = False,
                  analysis_path: Optional[Path] = None, client=None,
                  now: Optional[_dt.datetime] = None) -> Tuple[Optional[AiReport], str]:
    """Napravi AI izvještaj za zvaničnu analizu današnjeg dana mečeva (ili za zadati fajl analize).

    Vraća (izvještaj ili None, poruka). Poruka koja počinje sa ``SKIP`` znači da nije bilo šta da se radi.
    """
    if client is None and not settings.anthropic_api_key:
        return None, "SKIP: ANTHROPIC_API_KEY nije postavljen u .env — AI izvještaj se ne pravi"
    if analysis_path is not None:
        src = Path(analysis_path)
        if not src.exists():
            raise AiReportError(f"Fajl analize ne postoji: {src}")
    else:
        gdate = current_game_date(now)
        src = official_analysis_for(settings.history_dir, gdate)
        if src is None:
            return None, (f"SKIP: nema snimljene analize za mečeve {gdate.strftime('%d.%m.%Y')} — "
                          f"AI izvještaj se pravi tek poslije analize")
    existing = report_for_source(settings.ai_history_dir, src.name)
    if existing and not force:
        return None, f"SKIP: AI izvještaj za {src.name} već postoji ({existing.get('file')})"
    m = _TS_RE.search(src.name)
    report = generate_ai_report(pd.read_csv(src), settings, client=client, injuries=_load_injuries(settings),
                                source_name=src.name, timestamp=m.group(1) if m else None, tag=analysis_tag(src),
                                log=log, track_record=model_track_record(settings.history_dir))
    usage = report.data["usage"]
    cost = f", oko {usage['cost_usd']:.2f} USD" if usage.get("cost_usd") is not None else ""
    return report, (f"{len(report.data['picks'])} AI izbora snimljeno u {report.report_path.name} "
                    f"(model {report.data['model']}, tokeni {usage['input_tokens']}/{usage['output_tokens']}{cost})")
