"""NBA Quant Engine — paket sa svom logikom aplikacije.

Moduli:
  config      – podešavanja (sezona, putanje, API ključ iz .env)
  teams       – mape timova i normalizacija kratica
  utils       – pomoćne funkcije (imena, brojevi, status ozljeda)
  offer       – parsiranje dnevne ponude i ručnih unosa
  loaders     – učitavanje CSV fajlova iz data/
  model       – projekcija poena po igraču (formule su nepromijenjene)
  pipeline    – kompletna dnevna analiza: projekcije → Monte Carlo → rangiranje
  evaluation  – ocjena modela na stvarnim rezultatima
  schedule    – raspored/stanje mečeva sa ESPN-a
  history     – snimanje rezultata u history/
  odds_api    – dnevna ponuda sa The Odds API
  refresh     – osvježavanje podataka sa NBA API-ja
"""

__version__ = "2.0.0"
