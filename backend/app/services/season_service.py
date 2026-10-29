from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import DEV_USER_EMAIL
from app.repositories.season_repository import SeasonRepository


class SeasonService:
    def __init__(self, repository: SeasonRepository | None = None):
        self.repository = repository or SeasonRepository()

    def list_for_series(self, db: Session, series_id: UUID):
        return self.repository.list_for_series(db, series_id, DEV_USER_EMAIL)

    def create(self, db: Session, series_id: UUID, payload):
        if not self.repository.can_create_additional(db, series_id):
            raise PermissionError("Use season planning to create the first season, or finish the current season story before creating another season")
        result = self.repository.create(db, series_id, DEV_USER_EMAIL, payload)
        if result is None:
            db.rollback()
        else:
            db.commit()
        return result

    def update(self, db: Session, season_id: UUID, payload):
        result = self.repository.update(db, season_id, DEV_USER_EMAIL, payload)
        if result is None:
            db.rollback()
        else:
            db.commit()
        return result

    def update_pipeline(self, db: Session, season_id: UUID, payload):
        result = self.repository.update_pipeline(db, season_id, DEV_USER_EMAIL, payload)
        if result is None:
            db.rollback()
        else:
            db.commit()
        return result

    def get_pipeline(self, db: Session, season_id: UUID):
        return self.repository.get_pipeline(db, season_id, DEV_USER_EMAIL)

    def list_episodes(self, db: Session, season_id: UUID):
        return self.repository.list_episodes(db, season_id, DEV_USER_EMAIL)
