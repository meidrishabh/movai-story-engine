from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


class CatalogRepository:
    def ensure_dev_user(self, db: Session, email: str):
        return db.execute(
            text("""INSERT INTO users (email, display_name, is_active)
                VALUES (:email, 'MovAI Development User', TRUE)
                ON CONFLICT (email) DO UPDATE SET is_active = TRUE, updated_at = now()
                RETURNING id"""),
            {"email": email},
        ).scalar_one()

    def list_projects(self, db: Session, email: str):
        result = db.execute(text("""SELECT p.id, p.title, p.description, p.settings,
                p.created_at, p.updated_at, COUNT(DISTINCT s.id) AS series_count
                FROM projects p JOIN users u ON u.id = p.owner_id LEFT JOIN series s ON s.project_id = p.id
                WHERE u.email = :email GROUP BY p.id, p.title, p.description, p.settings, p.created_at, p.updated_at
                ORDER BY p.created_at DESC"""), {"email": email})
        return [dict(row) for row in result.mappings().all()]

    def create_project(self, db: Session, email: str, title: str, description: str | None):
        owner_id = self.ensure_dev_user(db, email)
        row = db.execute(text("""INSERT INTO projects (owner_id, title, description)
            VALUES (:owner_id, :title, :description)
            RETURNING id, owner_id, title, description, settings, created_at, updated_at"""),
            {"owner_id": owner_id, "title": title, "description": description}).mappings().first()
        return dict(row) if row else None

    def get_project(self, db: Session, project_id: UUID, email: str):
        row = db.execute(text("""SELECT p.id, p.owner_id, p.title, p.description, p.settings,
                p.created_at, p.updated_at, COUNT(DISTINCT s.id) AS series_count
                FROM projects p JOIN users u ON u.id = p.owner_id LEFT JOIN series s ON s.project_id = p.id
                WHERE p.id = :project_id AND u.email = :email
                GROUP BY p.id, p.owner_id, p.title, p.description, p.settings, p.created_at, p.updated_at"""),
            {"project_id": str(project_id), "email": email}).mappings().first()
        return dict(row) if row else None

    def update_project(self, db: Session, project_id: UUID, email: str, title, description):
        row = db.execute(text("""UPDATE projects p SET title = COALESCE(:title, p.title),
                description = COALESCE(:description, p.description) FROM users u
                WHERE p.id = :project_id AND u.id = p.owner_id AND u.email = :email
                RETURNING p.id, p.owner_id, p.title, p.description, p.settings, p.created_at, p.updated_at"""),
            {"project_id": str(project_id), "email": email, "title": title, "description": description}).mappings().first()
        return dict(row) if row else None

    def list_project_series(self, db: Session, project_id: UUID, email: str):
        result = db.execute(text("""SELECT s.id, s.project_id, s.title, s.premise, s.genre, s.language_code,
                s.visual_style, s.continuity_notes, s.created_at, s.updated_at, COUNT(DISTINCT e.id) AS episode_count
                FROM series s JOIN projects p ON p.id = s.project_id JOIN users u ON u.id = p.owner_id
                LEFT JOIN episodes e ON e.series_id = s.id WHERE s.project_id = :project_id AND u.email = :email
                GROUP BY s.id, s.project_id, s.title, s.premise, s.genre, s.language_code, s.visual_style,
                         s.continuity_notes, s.created_at, s.updated_at ORDER BY s.created_at"""),
            {"project_id": str(project_id), "email": email})
        return [dict(row) for row in result.mappings().all()]

    def create_series(self, db: Session, project_id: UUID, email: str, payload):
        row = db.execute(text("""INSERT INTO series (project_id, title, premise, genre, language_code, visual_style)
            SELECT p.id, :title, :premise, :genre, :language_code, :visual_style FROM projects p JOIN users u ON u.id = p.owner_id
            WHERE p.id = :project_id AND u.email = :email
            RETURNING id, project_id, title, premise, genre, language_code, visual_style, created_at, updated_at"""),
            {"project_id": str(project_id), "email": email, "title": payload.title, "premise": payload.premise,
             "genre": payload.genre, "language_code": payload.language_code, "visual_style": payload.visual_style}).mappings().first()
        return dict(row) if row else None

    def list_series(self, db: Session, email: str):
        result = db.execute(text("""SELECT s.id, s.project_id, s.title, s.premise, s.genre, s.language_code,
                s.visual_style, s.created_at, s.updated_at, COUNT(DISTINCT se.id) AS season_count,
                COUNT(DISTINCT e.id) AS episode_count FROM series s JOIN projects p ON p.id = s.project_id
                JOIN users u ON u.id = p.owner_id LEFT JOIN seasons se ON se.series_id = s.id
                LEFT JOIN episodes e ON e.series_id = s.id WHERE u.email = :email
                GROUP BY s.id, s.project_id, s.title, s.premise, s.genre, s.language_code, s.visual_style,
                         s.created_at, s.updated_at ORDER BY s.created_at DESC"""), {"email": email})
        return [dict(row) for row in result.mappings().all()]

    def get_series(self, db: Session, series_id: UUID, email: str):
        row = db.execute(text("""SELECT s.id, s.project_id, s.title, s.premise, s.genre, s.language_code,
                s.visual_style, s.continuity_notes, s.created_at, s.updated_at FROM series s
                JOIN projects p ON p.id = s.project_id JOIN users u ON u.id = p.owner_id
                WHERE s.id = :series_id AND u.email = :email"""),
            {"series_id": str(series_id), "email": email}).mappings().first()
        return dict(row) if row else None

    def update_series(self, db: Session, series_id: UUID, email: str, payload):
        row = db.execute(text("""UPDATE series s SET title = COALESCE(:title, s.title), premise = COALESCE(:premise, s.premise),
                genre = COALESCE(:genre, s.genre), language_code = COALESCE(:language_code, s.language_code),
                visual_style = COALESCE(:visual_style, s.visual_style) FROM projects p JOIN users u ON u.id = p.owner_id
                WHERE s.id = :series_id AND p.id = s.project_id AND u.email = :email
                RETURNING s.id, s.project_id, s.title, s.premise, s.genre, s.language_code, s.visual_style,
                          s.continuity_notes, s.created_at, s.updated_at"""),
            {"series_id": str(series_id), "email": email, "title": payload.title, "premise": payload.premise,
             "genre": payload.genre, "language_code": payload.language_code, "visual_style": payload.visual_style}).mappings().first()
        return dict(row) if row else None
