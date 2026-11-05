"""AI izvještaj: tabela kandidata, upit, provjera izbora, snimanje i zasebno poravnanje. Sve bez mreže (lažni klijent)."""
import datetime as dt
import json
from types import SimpleNamespace

import pandas as pd
import pytest

from nba_engine import ai_report as A
from nba_engine import settle as S
from nba_engine.config import Settings
from nba_engine.daily import stage_ai


# ---------------------------------------------------------------------------
# pomoćno
# ---------------------------------------------------------------------------

def _settings(tmp_path, monkeypatch, key="test-key"):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    s = Settings.load(data_dir=tmp_path / "data", season="2026-27", env_file=tmp_path / "no.env",
                      history_dir=tmp_path / "history")
    s.anthropic_api_key = key
    return s


def _analysis():
    """12 igrača; model kaže OVER za sve osim Conleya (UNDER) i Dosunmua (NO VALUE)."""
    names = ["Luka Dončić", "Jaxson Hayes", "Mike Conley", "Rui Hachimura", "Ayo Dosunmu", "Jamal Murray",
             "Nikola Jokić", "Devin Booker", "Jalen Brunson", "Trae Young", "Zach Edey", "Klay Thompson"]
    n = len(names)
    return pd.DataFrame({
        "Player": names,
        "TEAM_ABBR": ["LAL", "UTA", "BOS", "LAL", "MIN", "DEN", "DEN", "PHX", "NYK", "WAS", "MEM", "MIA"],
        "OPP_TEAM": ["OKC", "OKC", "SAS", "OKC", "SAS", "TOR", "TOR", "GSW", "CHI", "ATL", "HOU", "ORL"],
        "Is Home": [True, True, False, True, False, True, True, False, True, False, True, False],
        "Line": [27.5, 4.5, 10.5, 11.5, 9.5, 23.5, 28.5, 25.5, 26.5, 24.5, 12.5, 13.5],
        "Over Odds": [1.9, 2.07, 1.85, 1.9, 1.9, 1.96, 1.9, 1.9, 1.9, 1.9, 1.9, 1.9],
        "Under Odds": [1.9, 1.74, 1.95, 1.9, 1.9, 1.93, 1.9, 1.9, 1.9, 1.9, 1.9, 1.9],
        "Final Projection": [25.0, 6.5, 9.0, 13.0, 13.7, 31.1, 30.0, 27.0, 28.0, 26.0, 14.0, 15.0],
        "Projection Edge": [2.0, 2.0, -1.5, 1.5, 4.2, 4.9, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5],
        "P(Over)%": [60.0, 62.0, 40.0, 58.0, 52.0, 69.5] + [57.0] * (n - 6),
        "P(Under)%": [40.0, 38.0, 60.0, 42.0, 48.0, 30.5] + [43.0] * (n - 6),
        "Pick Confidence %": [60.0, 62.0, 60.0, 58.0, 52.0, 69.5] + [57.0] * (n - 6),
        "Model Pick": ["OVER", "OVER", "UNDER", "OVER", "NO VALUE"] + ["OVER"] * (n - 5),
        "Best EV %": [12.0, 35.0, 8.0, 5.0, -1.0] + [6.0] * (n - 5),
        "True Score": [float(n - i) for i in range(n)],
        "B2B Team": [False] * n,
    })


def _injuries():
    return pd.DataFrame({
        "PLAYER": ["Rui Hachimura", "Austin Reaves", "Tyrese Haliburton"],
        "TEAM_ABBR": ["LAL", "LAL", "IND"],
        "STATUS": ["QUESTIONABLE", "OUT", "OUT"],
        "DESCRIPTION": ["Hachimura (ankle) is questionable. " + "x" * 300, "Reaves (hamstring) is out.", "Out for season."],
    })


def _payload(n=10, **overrides):
    """Odgovor modela: prvih n igrača iz _analysis(); prvi je namjerno UNDER (suprotno od modela)."""
    names = _analysis()["Player"].tolist()
    picks = [{"player": names[i], "side": "UNDER" if i == 0 else "OVER", "confidence": 62 - i,
              "reason": f"Razlog {i + 1}.", "risk": f"Rizik {i + 1}."} for i in range(n)]
    return {"summary": "Miran dan bez velikih iznenađenja.", "picks": picks, **overrides}


class _Stream:
    def __init__(self, message):
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._message


class _Messages:
    def __init__(self, client, beta):
        self.client, self.is_beta = client, beta

    def stream(self, **kwargs):
        self.client.calls.append(("beta" if self.is_beta else "plain", kwargs))
        if self.is_beta and self.client.beta_error is not None:
            raise self.client.beta_error
        return _Stream(self.client.message)


class FakeClient:
    """Oponaša anthropic.Anthropic: client.beta.messages.stream(...) i client.messages.stream(...)."""

    def __init__(self, payload=None, text=None, stop_reason="end_turn", beta_error=None, model="claude-opus-5-5"):
        body = text if text is not None else json.dumps(payload if payload is not None else _payload())
        self.message = SimpleNamespace(
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=body)],
            stop_reason=stop_reason, model=model, usage=SimpleNamespace(input_tokens=20000, output_tokens=5000))
        self.calls, self.beta_error = [], beta_error
        self.beta = SimpleNamespace(messages=_Messages(self, True))
        self.messages = _Messages(self, False)


def _bad_request(msg="fallbacks: Extra inputs are not permitted"):
    import anthropic
    import httpx2
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.BadRequestError(msg, response=httpx2.Response(400, request=req), body=None)


# ---------------------------------------------------------------------------
# ulaz za model
# ---------------------------------------------------------------------------

def test_candidates_table_and_prompt():
    df = pd.concat([_analysis(), _analysis().head(1)], ignore_index=True)      # duplikat igrača se izbacuje
    cands = A.build_candidates(df, _injuries())
    assert len(cands) == 12 and cands["player"].is_unique
    assert {"player", "team", "opp", "home", "line", "over_odds", "under_odds", "proj", "p_over", "model_pick", "status"} <= set(cands.columns)
    assert cands["home"].tolist()[:3] == [1, 1, 0] and cands["b2b"].eq(0).all()
    assert cands.loc[cands["player"] == "Rui Hachimura", "status"].item() == "QUESTIONABLE"
    assert cands.loc[cands["player"] == "Mike Conley", "status"].item() == ""

    inj = A.injury_lines(_injuries(), cands["team"].tolist() + cands["opp"].tolist())
    assert "LAL | Austin Reaves | OUT | Reaves (hamstring) is out." in inj
    assert "Haliburton" not in inj                                             # IND nije u ponudi
    assert max(len(line) for line in inj.splitlines()) < 230                   # opis je skraćen

    system, user = A.build_prompt(cands, 10, dt.date(2026, 10, 30), "2026-27", inj, "Dosadašnji učinak: OVER 3 od 5.")
    assert "10 NAJSIGURNIJIH" in system and "ijekavicom" in system and "Najviše 3 izbora iz istog meča" in system
    assert "30.10.2026" in user and "Igrača u ponudi: 12" in user and "Dosadašnji učinak" in user
    assert "Luka Dončić,LAL,OKC,1,27.5,1.9,1.9" in user and "OBJAŠNJENJE KOLONA" in user
    assert A.build_prompt(cands, 10, dt.date(2026, 10, 30), "2026-27")[1].count("Lista povreda nije dostupna") == 1


def test_select_picks_keeps_only_valid_choices():
    df = _analysis()
    raw = [{"player": "Luka Doncic", "side": "under", "confidence": "61", "reason": "r", "risk": "k"},   # bez kvačica, mala slova
           {"player": "Nepostojeći Igrač", "side": "OVER", "confidence": 60, "reason": "", "risk": ""},
           {"player": "Luka Dončić", "side": "OVER", "confidence": 60, "reason": "", "risk": ""},           # duplikat
           {"player": "Mike Conley", "side": "MOŽDA", "confidence": 60, "reason": "", "risk": ""},
           {"player": "Jaxson Hayes", "side": "OVER", "confidence": 58.6, "reason": "r2", "risk": "k2"},
           {"player": "Jamal Murray", "side": "OVER", "confidence": 55, "reason": "r3", "risk": "k3"}]
    chosen, warnings = A.select_picks(raw, df, n=2)
    assert [(c["row"], c["side"], c["confidence"]) for c in chosen] == [(0, "UNDER", 61), (1, "OVER", 59)]   # treći odbačen: n=2
    assert len(warnings) == 3 and "nije u ponudi" in warnings[0] and "dva puta" in warnings[1]


# ---------------------------------------------------------------------------
# poziv i snimanje
# ---------------------------------------------------------------------------

def test_generate_report_writes_ai_analysis_and_report(tmp_path, monkeypatch):
    s = _settings(tmp_path, monkeypatch)
    client = FakeClient()
    rep = A.generate_ai_report(_analysis(), s, client=client, injuries=_injuries(), source_name="analysis_2026-10-30_22-30-40_daily.csv",
                               timestamp="2026-10-30_22-30-40", tag="daily", track_record="Dosadašnji učinak...")
    # zahtjev: strukturisan odgovor + zaštita od odbijanja
    kind, req = client.calls[0]
    assert kind == "beta" and len(client.calls) == 1
    assert req["model"] == "claude-opus-5-5" and req["fallbacks"] == "default" and req["betas"] == [A.FALLBACK_BETA]
    assert req["output_config"]["format"]["type"] == "json_schema" and req["output_config"]["effort"] == A.AI_EFFORT
    assert "temperature" not in req and "thinking" not in req
    assert "Luka Dončić" in req["messages"][0]["content"]

    # fajl u formatu analize: Model Pick je strana koju je izabrao AI
    assert rep.analysis_path == s.ai_history_dir / "analysis_2026-10-30_22-30-40_daily.csv"
    saved = pd.read_csv(rep.analysis_path)
    assert len(saved) == 10 and saved["AI Rank"].tolist() == list(range(1, 11))
    assert saved.loc[0, "Player"] == "Luka Dončić" and saved.loc[0, "Model Pick"] == "UNDER" and saved.loc[0, "Engine Pick"] == "OVER"
    assert saved.loc[0, "Pick Confidence %"] == 40.0                      # vjerovatnoća modela za AI stranu
    assert saved.loc[4, "Player"] == "Ayo Dosunmu" and saved.loc[4, "Engine Pick"] == "NO VALUE" and saved.loc[4, "Model Pick"] == "OVER"
    assert saved.loc[1, "AI Reason"] == "Razlog 2." and saved.loc[1, "AI Confidence %"] == 61

    # izvještaj
    data = json.loads(rep.report_path.read_text(encoding="utf-8"))
    assert rep.report_path.name == "report_2026-10-30_22-30-40_daily.json" and data["official"] is True
    assert data["game_date"] == "2026-10-30" and data["source_analysis"].endswith("_daily.csv") and data["candidates"] == 12
    assert data["picks"][0] == {"rank": 1, "player": "Luka Dončić", "team": "LAL", "opp": "OKC", "home": True, "side": "UNDER",
                                "line": 27.5, "odds": 1.9, "projection": 25.0, "model_prob": 40.0, "engine_pick": "OVER",
                                "confidence": 62, "reason": "Razlog 1.", "risk": "Rizik 1."}
    assert data["usage"] == {"input_tokens": 20000, "output_tokens": 5000, "cost_usd": 0.18} and data["warnings"] == []
    md = A.render_markdown(data)
    assert "**1. Luka Dončić** — **UNDER 27.5** @ 1.9  \nLAL–OKC, kod kuće · sigurnost 62 %\n\nRazlog 1.\n\n⚠️ Rizik 1.\n" in md
    assert list(A.picks_table(data).columns)[:4] == ["#", "Igrač", "Meč", "Izbor"]


def test_fewer_valid_picks_is_reported_not_fatal(tmp_path, monkeypatch):
    s = _settings(tmp_path, monkeypatch)
    payload = _payload(3)
    payload["picks"][1]["player"] = "Izmišljeni Igrač"
    rep = A.generate_ai_report(_analysis(), s, client=FakeClient(payload), timestamp="2026-10-30_22-30-40")
    assert len(rep.data["picks"]) == 2 and rep.data["official"] is False
    assert any("nije u ponudi" in w for w in rep.data["warnings"]) and any("umjesto 10" in w for w in rep.data["warnings"])
    with pytest.raises(A.AiReportError, match="Nijedan AI izbor"):
        A.generate_ai_report(_analysis(), s, client=FakeClient({"summary": "", "picks": [{"player": "X", "side": "OVER"}]}))


def test_call_model_retries_without_fallback_option():
    client = FakeClient(beta_error=_bad_request())
    lines = []
    msg = A.call_model(client, "claude-opus-5-5", "sistem", "korisnik", log=lines.append)
    assert [k for k, _ in client.calls] == ["beta", "plain"] and msg is client.message
    assert "fallbacks" not in client.calls[1][1] and "betas" not in client.calls[1][1]
    assert client.calls[1][1]["output_config"]["format"]["type"] == "json_schema" and lines


def test_refusal_truncation_and_bad_json_raise(tmp_path, monkeypatch):
    s = _settings(tmp_path, monkeypatch)
    for client, pattern in ((FakeClient(stop_reason="refusal"), "odbio"), (FakeClient(stop_reason="max_tokens"), "prekinut"),
                            (FakeClient(text="nije json"), "JSON"), (FakeClient(text='{"summary": "x"}'), "picks")):
        with pytest.raises(A.AiReportError, match=pattern):
            A.generate_ai_report(_analysis(), s, client=client)
    assert not s.ai_history_dir.exists() or not list(s.ai_history_dir.iterdir())       # ništa nije snimljeno
    with pytest.raises(A.AiReportError, match="prazna"):
        A.generate_ai_report(pd.DataFrame(), s, client=FakeClient())


def test_missing_key_and_friendly_errors(tmp_path, monkeypatch):
    s = _settings(tmp_path, monkeypatch, key="")
    with pytest.raises(A.AiReportError, match="ANTHROPIC_API_KEY"):
        A.make_client(s)
    import anthropic
    import httpx2
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    auth = anthropic.AuthenticationError("invalid x-api-key", response=httpx2.Response(401, request=req), body=None)
    assert "ANTHROPIC_API_KEY" in A.friendly_error(auth, "claude-opus-5-5")
    assert "nema kredita" in A.friendly_error(_bad_request("Your credit balance is too low to access the Anthropic API."), "m")
    assert "nije prihvatio" in A.friendly_error(_bad_request("nešto drugo"), "m")
    assert "nije uspio" in A.friendly_error(ValueError("x"), "m")
    # greška API-ja iz oba pokušaja stiže korisniku kao jasna poruka
    s2 = _settings(tmp_path, monkeypatch)
    client = FakeClient(beta_error=_bad_request("Your credit balance is too low"))
    client.messages.stream = lambda **kw: (_ for _ in ()).throw(_bad_request("Your credit balance is too low"))
    with pytest.raises(A.AiReportError, match="nema kredita"):
        A.generate_ai_report(_analysis(), s2, client=client)


def test_estimate_cost():
    assert A.estimate_cost("claude-opus-5-5", 1_000_000, 1_000_000) == 24.0
    assert A.estimate_cost("claude-sonnet-5-5", 20000, 5000) == 0.09
    assert A.estimate_cost("claude-haiku-5-5", 100000, 10000) == 0.015
    assert A.estimate_cost("nepoznat-model", 1000, 1000) is None


# ---------------------------------------------------------------------------
# dnevni tok: izvještaj za današnju zvaničnu analizu, bez duplog plaćanja, zasebno poravnanje
# ---------------------------------------------------------------------------

def test_run_for_today_skips_reuses_and_never_overwrites(tmp_path, monkeypatch):
    now = dt.datetime(2026, 10, 30, 22, 31)
    no_key = _settings(tmp_path, monkeypatch, key="")
    assert A.run_for_today(no_key, now=now) == (None, "SKIP: ANTHROPIC_API_KEY nije postavljen u .env — AI izvještaj se ne pravi")
    assert stage_ai(no_key, lambda m: None).startswith("SKIP: ANTHROPIC_API_KEY")

    s = _settings(tmp_path, monkeypatch)
    rep, msg = A.run_for_today(s, client=FakeClient(), now=now)
    assert rep is None and msg.startswith("SKIP: nema snimljene analize za mečeve 30.10.2026")

    s.history_dir.mkdir(parents=True)
    _analysis().to_csv(s.history_dir / "analysis_2026-10-30_19-00-00.csv", index=False)        # ručna, nije zvanična
    _analysis().to_csv(s.history_dir / "analysis_2026-10-30_22-30-40_daily.csv", index=False)
    client = FakeClient()
    rep, msg = A.run_for_today(s, client=client, now=now)
    assert rep.report_path.name == "report_2026-10-30_22-30-40_daily.json" and rep.data["official"] is True
    assert rep.data["source_analysis"] == "analysis_2026-10-30_22-30-40_daily.csv"
    assert msg.startswith("10 AI izbora snimljeno u report_2026-10-30_22-30-40_daily.json") and "oko 0.18 USD" in msg

    again, msg2 = A.run_for_today(s, client=client, now=now)                                   # isti dan drugi put: bez poziva
    assert again is None and "već postoji" in msg2 and len(client.calls) == 1

    forced, _ = A.run_for_today(s, client=client, now=now, force=True)                          # novi fajl, stari ostaje
    assert forced.report_path.name == "report_2026-10-30_22-30-41_daily.json" and rep.report_path.exists()
    assert forced.data["game_date"] == "2026-10-30" and len(A.list_reports(s.ai_history_dir)) == 2
    assert A.latest_report(s.ai_history_dir)["file"] == forced.report_path.name
    assert A.cost_summary(s.ai_history_dir, month="2026-10") == {"reports": 2, "cost_usd": 0.36, "unknown": 0}
    assert A.cost_summary(s.ai_history_dir, month="2026-11")["reports"] == 0


def test_latest_report_prefers_official_of_latest_day(tmp_path, monkeypatch):
    s = _settings(tmp_path, monkeypatch)
    A.generate_ai_report(_analysis(), s, client=FakeClient(), timestamp="2026-10-30_22-30-40", tag="daily")
    A.generate_ai_report(_analysis(), s, client=FakeClient(), timestamp="2026-10-30_23-10-00")       # ručni, kasnije istog dana
    assert A.latest_report(s.ai_history_dir)["file"] == "report_2026-10-30_22-30-40_daily.json"
    A.generate_ai_report(_analysis(), s, client=FakeClient(), timestamp="2026-10-31_18-00-00")       # novi dan: ručni je jedini
    assert A.latest_report(s.ai_history_dir)["file"] == "report_2026-10-31_18-00-00.json"
    assert A.latest_report(tmp_path / "nema") is None and A.report_for_source(s.ai_history_dir, "") is None


def test_ai_picks_settle_into_their_own_ledger(tmp_path, monkeypatch):
    s = _settings(tmp_path, monkeypatch)
    payload = {"summary": "s", "picks": [
        {"player": "Luka Dončić", "side": "UNDER", "confidence": 60, "reason": "", "risk": ""},     # 24 < 27.5 → WIN
        {"player": "Jaxson Hayes", "side": "UNDER", "confidence": 55, "reason": "", "risk": ""},    # 6 > 4.5 → LOSS (model je rekao OVER)
        {"player": "Mike Conley", "side": "OVER", "confidence": 54, "reason": "", "risk": ""},      # 9 < 10.5 → LOSS
        {"player": "Ayo Dosunmu", "side": "OVER", "confidence": 53, "reason": "", "risk": ""}]}     # nije igrao → VOID
    A.generate_ai_report(_analysis(), s, client=FakeClient(payload), timestamp="2026-10-30_22-30-40", tag="daily", n=4)
    A.generate_ai_report(_analysis(), s, client=FakeClient(_payload(3)), timestamp="2026-10-30_19-00-00", n=3)   # ručni: ne ocjenjuje se
    game_log = pd.DataFrame({
        "PLAYER_NAME": ["Luka Doncic", "Jaxson Hayes", "Mike Conley"], "TEAM_ABBREVIATION": ["LAL", "UTA", "BOS"],
        "GAME_DATE": ["2026-10-30"] * 3, "MATCHUP": ["LAL vs. OKC", "UTA vs. OKC", "BOS @ SAS"],
        "PTS": [24, 6, 9], "MIN": [35.0, 20.0, 22.0]})
    actuals = S.actuals_from_game_log(game_log)
    events = S.settle_history(s.ai_history_dir, provider=lambda season: actuals, today=dt.date(2026, 10, 31))
    assert sorted(e["status"] for e in events) == ["settled", "superseded"]
    ledger = S.load_ledger(s.ai_history_dir)
    row = ledger.iloc[0]
    assert len(ledger) == 1 and row["Analysis"] == "analysis_2026-10-30_22-30-40_daily.csv"
    assert (row["Picks"], row["Wins"], row["Losses"], row["Void"]) == (4, 1, 2, 1)
    assert row["Profit"] == pytest.approx(0.9 - 2.0) and row["ROI %"] == pytest.approx(-36.67, abs=0.01)
    assert S.load_ledger(s.history_dir).empty                                  # ledger modela se ne dira
    month = S.monthly_summary(ledger)
    assert month.loc[0, "Month"] == "2026-10" and (month.loc[0, "Bets"], month.loc[0, "Wins"], month.loc[0, "Days"]) == (3, 1, 1)
