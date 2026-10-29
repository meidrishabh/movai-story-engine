from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import DEV_USER_EMAIL
from app.repositories.catalog_repository import CatalogRepository


class CatalogService:
    def __init__(self, repository: CatalogRepository | None = None):
        self.repository = repository or CatalogRepository()

    def list_projects(self, db: Session):
        return self.repository.list_projects(db, DEV_USER_EMAIL)

    def create_project(self, db: Session, payload):
        project = self.repository.create_project(db, DEV_USER_EMAIL, payload.title, payload.description)
        if project is None:
            raise LookupError("Development user was not found")
        db.commit()
        return project

    def get_project(self, db: Session, project_id: UUID):
        return self.repository.get_project(db, project_id, DEV_USER_EMAIL)

    def update_project(self, db: Session, project_id: UUID, payload):
        result = self.repository.update_project(db, project_id, DEV_USER_EMAIL, payload.title, payload.description)
        if result is None:
            db.rollback()
        else:
            db.commit()
        return result

    def list_project_series(self, db: Session, project_id: UUID):
        return self.repository.list_project_series(db, project_id, DEV_USER_EMAIL)

    def create_series(self, db: Session, project_id: UUID, payload):
        result = self.repository.create_series(db, project_id, DEV_USER_EMAIL, payload)
        if result is None:
            db.rollback()
        else:
            db.commit()
        return result

    def list_series(self, db: Session):
        return self.repository.list_series(db, DEV_USER_EMAIL)

    def get_series(self, db: Session, series_id: UUID):
        return self.repository.get_series(db, series_id, DEV_USER_EMAIL)

    def update_series(self, db: Session, series_id: UUID, payload):
        result = self.repository.update_series(db, series_id, DEV_USER_EMAIL, payload)
        if result is None:
            db.rollback()
        else:
            db.commit()
        return result
