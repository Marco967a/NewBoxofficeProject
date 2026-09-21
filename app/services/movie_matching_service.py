import logging
from dataclasses import dataclass, field

from app.db import get_connection
from app.matching import (
    REVIEW_MIN_SCORE,
    Candidate,
    Decision,
    decide,
    estimate_italian_release,
    query_variants,
    rank_candidates,
    score_candidate,
)
from app.migrations import ensure_schema_current
from app.repositories.movie_repository import MovieRepository
from app.repositories.source_movie_repository import SourceMovieRepository
from app.tmdb_client import TMDBClient


logger = logging.getLogger(__name__)

MATCH_METHOD = "tmdb_search"
MAX_REFINED_CANDIDATES = 3
ALTERNATIVE_TITLES_BELOW = 0.9  # sotto questa somiglianza si cercano i titoli alternativi IT
MAX_STORED_CANDIDATES = 5


@dataclass
class MatchSummary:
    auto: int = 0
    needs_review: int = 0
    no_match: int = 0
    errors: int = 0
    lines: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.auto + self.needs_review + self.no_match + self.errors


class MovieMatchingService:
    """Collega i film della sorgente (source_movies) ai film TMDB (movies) e quindi a movie_id."""

    def __init__(self, tmdb_client: TMDBClient | None = None):
        self._tmdb_client = tmdb_client
        self.source_movie_repository = SourceMovieRepository()
        self.movie_repository = MovieRepository()

    @property
    def tmdb_client(self) -> TMDBClient:
        if self._tmdb_client is None:
            self._tmdb_client = TMDBClient()
        return self._tmdb_client

    # --- valutazione ------------------------------------------------------------------------

    def evaluate(self, title: str, estimated_release) -> tuple[list[Candidate], Decision]:
        """Cerca su TMDB, assegna i punteggi e decide. Nessuna scrittura sul DB."""
        results: dict[int, dict] = {}
        ranked: list[Candidate] = []

        for query in query_variants(title):
            for result in self.tmdb_client.search_movies(query):
                results.setdefault(result["id"], result)
            ranked = rank_candidates([score_candidate(title, estimated_release, r) for r in results.values()])
            if ranked and ranked[0].score >= REVIEW_MIN_SCORE:
                break  # trovato qualcosa di plausibile: le varianti più corte servirebbero solo a confondere

        # Verifica sui migliori candidati con dati più affidabili della sola ricerca: il titolo TMDB
        # può differire da quello di distribuzione italiano (titoli alternativi IT) e la data di
        # uscita in Italia (se pubblicata) conferma o smentisce l'omonimo / la riedizione.
        refined = []
        for candidate in ranked[:MAX_REFINED_CANDIDATES]:
            alternatives = (
                self.tmdb_client.get_alternative_titles(candidate.tmdb_id)
                if candidate.title_score < ALTERNATIVE_TITLES_BELOW else None
            )
            italian_dates = (
                self.tmdb_client.get_release_dates(candidate.tmdb_id)
                if candidate.title_score >= REVIEW_MIN_SCORE else None
            )
            refined.append(
                score_candidate(title, estimated_release, results[candidate.tmdb_id], alternatives, italian_dates)
            )

        ranked = rank_candidates(refined)
        decision = decide(ranked)

        return ranked, decision

    # --- operazioni -------------------------------------------------------------------------

    def link_legacy_rows(self, source_name: str = "comingsoon") -> dict[str, int]:
        with get_connection() as conn:
            ensure_schema_current(conn)
            counts = self.source_movie_repository.link_legacy_rows(conn, source_name)
        logger.info("Righe storiche collegate: %s", counts)
        return counts

    def resolve_pending(
        self,
        source_name: str = "comingsoon",
        statuses: tuple[str, ...] = ("unmatched",),
        limit: int | None = None,
        dry_run: bool = False,
    ) -> MatchSummary:
        summary = MatchSummary()

        with get_connection() as conn:
            ensure_schema_current(conn)
            pending = self.source_movie_repository.list_for_matching(conn, source_name, statuses, limit)
            logger.info("Film da abbinare: %s (stati=%s, dry_run=%s)", len(pending), statuses, dry_run)

            for item in pending:
                estimated = (
                    estimate_italian_release(item["first_week_start"], item["first_weeks_in_release"])
                    if item["first_week_start"] else None
                )
                try:
                    ranked, decision = self.evaluate(item["title"], estimated)
                    if not dry_run:
                        self._persist(conn, item["id"], ranked, decision)
                        conn.commit()
                except Exception as exc:
                    conn.rollback()
                    summary.errors += 1
                    summary.lines.append(f"[errore] {item['title']}: {exc}")
                    logger.warning("Match fallito per '%s': %s", item["title"], exc)
                    continue

                setattr(summary, decision.status, getattr(summary, decision.status) + 1)
                best = decision.best
                detail = (
                    f"{best.title!r} ({best.release_date}) tmdb={best.tmdb_id}" if best else "-"
                )
                summary.lines.append(
                    f"[{decision.status}] {item['title']!r} (uscita stimata {estimated}) -> {detail} | {decision.reason}"
                )

        return summary

    def _persist(self, conn, ref_id: int, ranked: list[Candidate], decision: Decision) -> None:
        if decision.status == "auto":
            details = self.tmdb_client.get_movie_details(decision.best.tmdb_id)
            self.movie_repository.upsert_movies(conn, [details])
            self.source_movie_repository.save_match(
                conn, ref_id, "auto", decision.best.tmdb_id, MATCH_METHOD, decision.best.score
            )
            self.source_movie_repository.replace_candidates(conn, ref_id, [])
        else:
            confidence = decision.best.score if decision.best else None
            self.source_movie_repository.save_match(
                conn, ref_id, decision.status, None, MATCH_METHOD, confidence
            )
            self.source_movie_repository.replace_candidates(conn, ref_id, ranked[:MAX_STORED_CANDIDATES])

    def set_manual_match(self, ref_id: int, tmdb_id: int) -> dict:
        """Abbinamento deciso da una persona: sovrascrive tutto e non viene più toccato dal resolver."""
        with get_connection() as conn:
            ensure_schema_current(conn)
            source = self.source_movie_repository.get(conn, ref_id)
            if source is None:
                raise ValueError(f"source_movies id={ref_id} inesistente")

            details = self.tmdb_client.get_movie_details(tmdb_id)  # fallisce se l'ID TMDB non esiste
            self.movie_repository.upsert_movies(conn, [details])
            self.source_movie_repository.save_match(conn, ref_id, "manual", tmdb_id, "manual", 1.0)
            self.source_movie_repository.replace_candidates(conn, ref_id, [])
        return {"source": source["title"], "tmdb_id": tmdb_id, "tmdb_title": details.get("title")}

    def set_no_match(self, ref_id: int) -> str:
        """Segna che il film non esiste su TMDB (es. documentario locale): il resolver non lo riprova."""
        with get_connection() as conn:
            ensure_schema_current(conn)
            source = self.source_movie_repository.get(conn, ref_id)
            if source is None:
                raise ValueError(f"source_movies id={ref_id} inesistente")
            self.source_movie_repository.save_match(conn, ref_id, "no_match", None, "manual", None)
            self.source_movie_repository.replace_candidates(conn, ref_id, [])
        return source["title"]

    def review_queue(self, source_name: str = "comingsoon") -> list[dict]:
        with get_connection() as conn:
            ensure_schema_current(conn)
            return self.source_movie_repository.list_needing_review(conn, source_name)
