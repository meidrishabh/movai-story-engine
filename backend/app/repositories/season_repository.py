from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


class SeasonRepository:
    def list_for_series(self, db: Session, series_id: UUID, email: str):
        result = db.execute(text("""SELECT se.id, se.series_id, se.season_number, se.title, se.synopsis,
                se.status, se.target_episode_count, se.target_episode_duration_seconds, se.climax_strategy,
                se.story_status, se.created_at, se.updated_at, COUNT(e.id) AS episode_count
                FROM seasons se JOIN series s ON s.id = se.series_id JOIN projects p ON p.id = s.project_id
                JOIN users u ON u.id = p.owner_id LEFT JOIN episodes e ON e.season_id = se.id
                WHERE se.series_id = :series_id AND u.email = :email
                GROUP BY se.id, se.series_id, se.season_number, se.title, se.synopsis, se.status,
                         se.target_episode_count, se.target_episode_duration_seconds, se.climax_strategy,
                         se.story_status, se.created_at, se.updated_at ORDER BY se.season_number"""),
            {"series_id": str(series_id), "email": email})
        return [dict(row) for row in result.mappings().all()]

    def can_create_additional(self, db: Session, series_id: UUID):
        return bool(db.execute(text("""SELECT EXISTS (SELECT 1 FROM seasons WHERE series_id = :series_id
            AND story_status IN ('analysis_complete', 'episode_planning_queued', 'episodes_generated', 'processed', 'complete', 'approved'))"""),
            {"series_id": str(series_id)}).scalar())

    def create(self, db: Session, series_id: UUID, email: str, payload):
        row = db.execute(text("""INSERT INTO seasons (series_id, season_number, title, synopsis)
            SELECT s.id, :season_number, :title, :synopsis FROM series s JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id WHERE s.id = :series_id AND u.email = :email
            RETURNING id, series_id, season_number, title, synopsis, status, created_at, updated_at"""),
            {"series_id": str(series_id), "email": email, "season_number": payload.season_number,
             "title": payload.title, "synopsis": payload.synopsis}).mappings().first()
        return dict(row) if row else None

    def update(self, db: Session, season_id: UUID, email: str, payload):
        row = db.execute(text("""UPDATE seasons se SET title = COALESCE(:title, se.title),
                synopsis = COALESCE(:synopsis, se.synopsis), status = COALESCE(:status, se.status)
                FROM series s JOIN projects p ON p.id = s.project_id JOIN users u ON u.id = p.owner_id
                WHERE se.id = :season_id AND s.id = se.series_id AND u.email = :email
                RETURNING se.id, se.series_id, se.season_number, se.title, se.synopsis, se.status, se.created_at, se.updated_at"""),
            {"season_id": str(season_id), "email": email, "title": payload.title,
             "synopsis": payload.synopsis, "status": payload.status}).mappings().first()
        return dict(row) if row else None

    def update_pipeline(self, db: Session, season_id: UUID, email: str, payload):
        row = db.execute(text("""UPDATE seasons se SET target_episode_count = COALESCE(:target_episode_count, se.target_episode_count),
                target_episode_duration_seconds = COALESCE(:target_episode_duration_seconds, se.target_episode_duration_seconds),
                climax_strategy = COALESCE(:climax_strategy, se.climax_strategy)
                FROM series s JOIN projects p ON p.id = s.project_id JOIN users u ON u.id = p.owner_id
                WHERE se.id = :season_id AND s.id = se.series_id AND u.email = :email
                RETURNING se.id, se.series_id, se.season_number, se.title, se.synopsis, se.target_episode_count,
                          se.target_episode_duration_seconds, se.climax_strategy, se.story_status, se.created_at, se.updated_at"""),
            {"season_id": str(season_id), "email": email, "target_episode_count": payload.target_episode_count,
             "target_episode_duration_seconds": payload.target_episode_duration_seconds,
             "climax_strategy": payload.climax_strategy}).mappings().first()
        return dict(row) if row else None

    def get_pipeline(self, db: Session, season_id: UUID, email: str):
        season = db.execute(text("""SELECT se.id, se.series_id, se.season_number, se.title, se.synopsis,
                se.target_episode_count, se.target_episode_duration_seconds, se.climax_strategy, se.story_status
                FROM seasons se JOIN series s ON s.id = se.series_id JOIN projects p ON p.id = s.project_id
                JOIN users u ON u.id = p.owner_id WHERE se.id = :season_id AND u.email = :email"""),
            {"season_id": str(season_id), "email": email}).mappings().first()
        if season is None:
            return None
        source = db.execute(text("""SELECT id, title, source_type, original_filename, status, created_at
            FROM story_sources WHERE season_id = :season_id ORDER BY created_at DESC LIMIT 1"""),
            {"season_id": str(season_id)}).mappings().first()
        script = db.execute(text("""SELECT id, version_number, title, summary, status, created_at, updated_at
            FROM master_scripts WHERE season_id = :season_id ORDER BY version_number DESC LIMIT 1"""),
            {"season_id": str(season_id)}).mappings().first()
        return {"season": dict(season), "source": dict(source) if source else None,
                "master_script": dict(script) if script else None}

    def list_episodes(self, db: Session, season_id: UUID, email: str):
        result = db.execute(text("""SELECT e.id, e.season_id, e.series_id, e.episode_number, e.title,
                e.synopsis, e.script, e.target_duration_seconds, e.status, e.created_at, e.updated_at
                FROM episodes e JOIN seasons se ON se.id = e.season_id JOIN series s ON s.id = se.series_id
                JOIN projects p ON p.id = s.project_id JOIN users u ON u.id = p.owner_id
                WHERE e.season_id = :season_id AND u.email = :email ORDER BY e.episode_number"""),
            {"season_id": str(season_id), "email": email})
        return [dict(row) for row in result.mappings().all()]
