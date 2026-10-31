from fastapi import APIRouter

from app.api.v1.adaptations import router as adaptations_router
from app.api.v1.appearance import router as appearance_router
from app.api.v1.analysis import router as analysis_router
from app.api.v1.analysis_results import router as analysis_results_router
from app.api.v1.catalog import router as catalog_router
from app.api.v1.characters import router as characters_router
from app.api.v1.entities import router as entities_router
from app.api.v1.generation import router as generation_router
from app.api.v1.references import router as references_router
from app.api.v1.seasons import router as seasons_router
from app.api.v1.season_story import router as season_story_router
from app.api.v1.system import router as system_router
from app.api.v1.production import router as production_router
from app.api.v1.workflow import router as workflow_router
from app.api.v1.uploads import router as uploads_router
from app.api.v1.story import router as story_router
from app.api.v1.structure import router as structure_router
from app.api.v1.style import router as style_router


router = APIRouter()
router.include_router(adaptations_router)
router.include_router(appearance_router)
router.include_router(analysis_router)
router.include_router(analysis_results_router)
router.include_router(catalog_router)
router.include_router(characters_router)
router.include_router(entities_router)
router.include_router(seasons_router)
router.include_router(season_story_router)
router.include_router(system_router)
router.include_router(production_router)
router.include_router(workflow_router)
router.include_router(uploads_router)
router.include_router(story_router)
router.include_router(structure_router)
router.include_router(generation_router)
router.include_router(style_router)
router.include_router(references_router)
