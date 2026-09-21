"""Punteggio di somiglianza tra un film della sorgente (ComingSoon) e i candidati TMDB.

Modulo puro, senza I/O. Il punteggio combina il titolo (peso 0.70), la compatibilità tra la data
di uscita TMDB e quella italiana stimata (0.25) e la popolarità (0.05, solo per spareggiare).
"""
import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from difflib import SequenceMatcher

WEIGHT_TITLE = 0.70
WEIGHT_DATE = 0.25
WEIGHT_POPULARITY = 0.05

# Soglie: auto-accetta solo se il migliore è alto E nettamente davanti al secondo.
AUTO_MIN_SCORE = 0.85
AUTO_MIN_MARGIN = 0.10
REVIEW_MIN_SCORE = 0.55

_ARTICLES = {"il", "lo", "la", "i", "gli", "le", "l", "un", "una", "the", "a", "an"}
_UNKNOWN_DATE_SCORE = 0.4


def normalize_title(title: str | None) -> str:
    """Minuscolo, senza accenti né punteggiatura, spazi compattati."""
    if not title:
        return ""
    decomposed = unicodedata.normalize("NFKD", title.casefold())
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", without_accents).strip()


def _strip_articles(normalized: str) -> str:
    tokens = normalized.split()
    while len(tokens) > 1 and tokens[0] in _ARTICLES:
        tokens = tokens[1:]
    return " ".join(tokens)


def title_similarity(a: str | None, b: str | None) -> float:
    """Somiglianza 0..1 tra due titoli, tollerante a articoli iniziali e a sottotitoli."""
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0

    sa, sb = _strip_articles(na), _strip_articles(nb)
    if sa == sb:
        return 0.97

    best = max(SequenceMatcher(None, na, nb).ratio(), SequenceMatcher(None, sa, sb).ratio())

    # "The Dog Stars - Le Stelle Dopo la Fine" vs "The Dog Stars": uno è il prefisso dell'altro.
    # Se il prefisso è il candidato (la sorgente ha in più un sottotitolo) l'indizio è più forte che
    # nel caso opposto (il candidato allunga il titolo della sorgente: "Election Day" vs
    # "Election Day - The Day Thailand ...", che è quasi sempre un altro film).
    short, long_ = sorted((sa, sb), key=len)
    if len(short.split()) >= 2 and (long_ + " ").startswith(short + " "):
        best = max(best, 0.88 if short == sb else 0.78)
    return best


def best_title_score(source_title: str, names: list[str | None]) -> float:
    return max((title_similarity(source_title, name) for name in names), default=0.0)


def estimate_italian_release(week_start: date, weeks_in_release: int | None) -> date:
    """Uscita italiana stimata: i film escono di giovedì, `weeks_in_release` conta la settimana corrente."""
    weeks = max((weeks_in_release or 1) - 1, 0)
    return week_start - timedelta(weeks=weeks)


def date_score(estimated: date | None, tmdb_release: date | None) -> float:
    """Compatibilità tra la data TMDB e l'uscita italiana stimata (1 = del tutto plausibile)."""
    if estimated is None or tmdb_release is None:
        return _UNKNOWN_DATE_SCORE
    delta = (estimated - tmdb_release).days  # >0: TMDB precede l'Italia (anteprime/festival)
    if -21 <= delta <= 150:
        return 1.0
    if 150 < delta <= 450:
        return 1.0 - 0.8 * (delta - 150) / 300
    if -90 <= delta < -21:
        return 1.0 - (-21 - delta) / 69
    return 0.0


def italian_release_score(estimated: date | None, italian_dates: list[date] | None) -> float | None:
    """Vicinanza tra l'uscita italiana stimata e le date IT pubblicate da TMDB.

    None se non ci sono dati: allora si ripiega su date_score(). Una data IT lontana dalla stima è
    un'evidenza forte CONTRO il candidato (omonimo o film diverso), quindi scende fino a 0.
    """
    if estimated is None or not italian_dates:
        return None
    gap = min(abs((estimated - d).days) for d in italian_dates)
    if gap <= 10:
        return 1.0
    if gap <= 45:
        return 1.0 - 0.8 * (gap - 10) / 35
    return 0.0


def popularity_score(popularity: float | None) -> float:
    if not popularity or popularity <= 0:
        return 0.0
    return min(1.0, math.log10(1 + popularity) / 3)


@dataclass(frozen=True)
class Candidate:
    tmdb_id: int
    title: str | None
    original_title: str | None
    release_date: date | None
    popularity: float | None
    title_score: float
    date_score: float
    score: float


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def score_candidate(
    source_title: str,
    estimated_release: date | None,
    result: dict,
    alternative_titles: list[str] | None = None,
    italian_release_dates: list[date] | None = None,
) -> Candidate:
    """Valuta un risultato di /search/movie rispetto al film della sorgente."""
    release = _parse_date(result.get("release_date"))
    names = [result.get("title"), result.get("original_title"), *(alternative_titles or [])]
    t = best_title_score(source_title, names)
    it_score = italian_release_score(estimated_release, italian_release_dates)
    d = it_score if it_score is not None else date_score(estimated_release, release)
    p = popularity_score(result.get("popularity"))
    return Candidate(
        tmdb_id=result["id"],
        title=result.get("title"),
        original_title=result.get("original_title"),
        release_date=release,
        popularity=result.get("popularity"),
        title_score=round(t, 3),
        date_score=round(d, 3),
        score=round(WEIGHT_TITLE * t + WEIGHT_DATE * d + WEIGHT_POPULARITY * p, 3),
    )


def rank_candidates(candidates: list[Candidate]) -> list[Candidate]:
    return sorted(candidates, key=lambda c: (-c.score, -(c.popularity or 0)))


@dataclass(frozen=True)
class Decision:
    status: str  # 'auto' | 'needs_review' | 'no_match'
    best: Candidate | None
    reason: str


def decide(ranked: list[Candidate]) -> Decision:
    """Auto-accetta solo un vincitore netto; i casi dubbi vanno in revisione."""
    if not ranked:
        return Decision("no_match", None, "nessun candidato")

    best = ranked[0]
    second = ranked[1].score if len(ranked) > 1 else 0.0
    margin = best.score - second

    if best.score >= AUTO_MIN_SCORE and margin >= AUTO_MIN_MARGIN:
        return Decision("auto", best, f"score={best.score} margine={margin:.3f}")
    if best.score >= REVIEW_MIN_SCORE:
        why = "margine troppo stretto" if best.score >= AUTO_MIN_SCORE else "punteggio sotto soglia"
        return Decision("needs_review", best, f"{why} (score={best.score} margine={margin:.3f})")
    return Decision("no_match", best, f"miglior punteggio {best.score} sotto {REVIEW_MIN_SCORE}")


def query_variants(title: str) -> list[str]:
    """Titolo completo, poi (se diverso) la parte prima di ':' o ' - ' e senza puntini iniziali."""
    variants = [title.strip()]
    cleaned = re.sub(r"^\.+\s*", "", title).strip()
    for candidate in (cleaned, re.split(r"\s+-\s+|:\s+", cleaned, maxsplit=1)[0].strip()):
        if candidate and candidate not in variants:
            variants.append(candidate)
    return variants
