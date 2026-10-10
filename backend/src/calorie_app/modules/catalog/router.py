"""Public official-channel reads. Products remain protected E3 design operations."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from calorie_app.core.errors import ApiError, error_response
from calorie_app.modules.catalog import OFFICIAL_PACKAGE_ID
from calorie_app.modules.catalog.export import read_published_artifact
from calorie_app.modules.catalog.models import (
    OfflineChannel,
    OfflinePackage,
    OfflinePackageRation,
    RationPageToken,
    RationPageTokenTombstone,
    RationVersion,
)
from calorie_app.modules.catalog.pagination import (
    PAGE_TTL,
    CursorNotConfigured,
    InvalidPageToken,
    PageCursor,
    database_now,
    decode_cursor,
    encode_cursor,
    prune_legacy_tokens,
)
from calorie_app.modules.catalog.repository import (
    active_package,
    components_for,
    manifest_data,
    ration_data,
    read_package,
)
from calorie_app.modules.catalog.schemas import ManifestDTO, RationDTO, RationPage, Uuid
from calorie_app.modules.catalog.validation import CatalogValidationError

router = APIRouter(prefix="/api/v1", tags=["catalog"])
ERRORS = {status: {"model": ApiError} for status in (404, 422, 503)}


class RationListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=100, ge=1, le=500)
    page_token: str | None = Field(default=None, min_length=1, max_length=4096)


class RationRevisionQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int | None = Field(default=None, ge=1, le=2147483647)


def _unavailable():
    return HTTPException(503, headers={"Retry-After": "30"})


def _latest(rations: list[dict]) -> list[dict]:
    latest = {}
    for ration in rations:
        latest[ration["ration_id"]] = ration
    return list(latest.values())


@router.get(
    "/rations",
    response_model=RationPage,
    operation_id="list_rations",
    responses=ERRORS | {410: {"model": ApiError}},
    description="Publiczne racje opublikowanego pakietu official v1. Token strony "
    "przypina package_id, release i limit na 60 minut bez przedłużania TTL. "
    "Nowe tokeny są podpisane i nie zapisują rekordu; stare UUID zachowują ważność "
    "i błąd page_expired po sprzątaniu. Nie jest to checkpoint synchronizacji.",
    openapi_extra={"security": []},
)
def list_rations(request: Request, query: Annotated[RationListQuery, Query()]):
    try:
        with Session(request.app.state.engine) as session, session.begin():
            prune_legacy_tokens(session)
            now = database_now(session)
            after = None
            if query.page_token is None:
                package = active_package(session, OFFICIAL_PACKAGE_ID)
                if package is None:
                    return {"items": [], "next_page_token": None}
                release = package.release
                expires_at = now + PAGE_TTL
            else:
                if query.page_token.startswith("rp1."):
                    try:
                        token = decode_cursor(
                            query.page_token, request.app.state.catalog_page_token_secret
                        )
                    except InvalidPageToken:
                        raise HTTPException(422) from None
                else:
                    try:
                        token_id = UUID(query.page_token)
                        if str(token_id) != query.page_token:
                            raise ValueError
                    except ValueError:
                        raise HTTPException(422) from None
                    token = session.get(RationPageToken, token_id)
                    if token is None:
                        expired = session.get(RationPageTokenTombstone, token_id)
                        if (
                            expired is not None
                            and expired.package_id == OFFICIAL_PACKAGE_ID
                            and expired.limit == query.limit
                        ):
                            return error_response(
                                request, 410, "page_expired", "Token strony wygasł."
                            )
                if (
                    token is None
                    or token.package_id != OFFICIAL_PACKAGE_ID
                    or token.limit != query.limit
                ):
                    raise HTTPException(422)
                if now >= token.expires_at:
                    return error_response(request, 410, "page_expired", "Token strony wygasł.")
                release, expires_at = token.release, token.expires_at
                after = (str(token.after_id), token.after_revision)
                package = session.get(OfflinePackage, (OFFICIAL_PACKAGE_ID, release))
                if package is None or package.state != "published":
                    raise HTTPException(404)
            rations = _latest(read_package(session, OFFICIAL_PACKAGE_ID, release)["rations"])
            if after is not None:
                rations = [r for r in rations if (r["ration_id"], r["revision"]) > after]
            page = rations[: query.limit]
            next_token = None
            if len(rations) > query.limit:
                last = page[-1]
                next_token = encode_cursor(
                    PageCursor(
                        package_id=OFFICIAL_PACKAGE_ID,
                        release=release,
                        after_id=UUID(last["ration_id"]),
                        after_revision=last["revision"],
                        limit=query.limit,
                        expires_at=expires_at,
                    ),
                    request.app.state.catalog_page_token_secret,
                )
            return {
                "items": page,
                "next_page_token": next_token,
            }
    except (SQLAlchemyError, OSError, CatalogValidationError, CursorNotConfigured):
        raise _unavailable() from None


@router.get(
    "/rations/{id}",
    response_model=RationDTO,
    operation_id="read_ration",
    responses=ERRORS,
    description="Bez revision: najnowsza wersja w aktywnym official release. "
    "Z revision: dokładna wersja należąca do opublikowanego wydania tego samego pakietu v1.",
    openapi_extra={"security": []},
)
def read_ration(request: Request, id: Uuid, query: Annotated[RationRevisionQuery, Query()]):
    try:
        with Session(request.app.state.engine) as session:
            stmt = (
                select(RationVersion)
                .join(
                    OfflinePackageRation,
                    and_(
                        OfflinePackageRation.ration_id == RationVersion.ration_id,
                        OfflinePackageRation.ration_revision == RationVersion.revision,
                    ),
                )
                .join(
                    OfflinePackage,
                    and_(
                        OfflinePackage.package_id == OfflinePackageRation.package_id,
                        OfflinePackage.release == OfflinePackageRation.release,
                    ),
                )
                .join(OfflineChannel, OfflineChannel.package_id == OfflinePackage.package_id)
                .where(
                    OfflineChannel.package_id == OFFICIAL_PACKAGE_ID,
                    OfflineChannel.kind == "official",
                    OfflinePackage.state == "published",
                    RationVersion.ration_id == id,
                )
            )
            if query.revision is None:
                stmt = stmt.where(OfflinePackage.release == OfflineChannel.active_release)
            else:
                stmt = stmt.where(RationVersion.revision == query.revision)
            row = session.scalar(stmt.order_by(RationVersion.revision.desc()).limit(1))
            if row is None:
                raise HTTPException(404)
            return ration_data(row, components_for(session, row.ration_id, row.revision))
    except (SQLAlchemyError, OSError, CatalogValidationError):
        raise _unavailable() from None


@router.get(
    "/offline-package/manifest",
    response_model=ManifestDTO,
    operation_id="read_manifest",
    responses=ERRORS,
    description="Aktywny opublikowany official package_id v1. "
    "Brak takiego wydania daje 404; demo jest przekazywane jako lokalny plik.",
    openapi_extra={"security": []},
)
def read_manifest(request: Request):
    try:
        with Session(request.app.state.engine) as session:
            package = active_package(session, OFFICIAL_PACKAGE_ID)
            if package is None:
                raise HTTPException(404)
            read_published_artifact(request.app.state.catalog_artifact_root, package, "official")
            return manifest_data(session, package, "official")
    except (SQLAlchemyError, OSError, CatalogValidationError):
        raise _unavailable() from None


@router.get(
    "/offline-package/{filename}",
    response_class=Response,
    operation_id="download_package",
    responses=ERRORS
    | {
        200: {
            "description": "Dokładne zarejestrowane bajty gzip. Bez Content-Encoding.",
            "content": {"application/gzip": {"schema": {"type": "string", "format": "binary"}}},
            "headers": {
                "Content-Length": {"schema": {"type": "integer", "minimum": 1, "maximum": 10485760}}
            },
        }
    },
    description="Niezmienne pliki opublikowanych wydań tego samego official pakietu v1; "
    "także starsze release. Pliki demo, draft i dowolne ścieżki są niedostępne.",
    openapi_extra={"security": []},
)
def download_package(
    request: Request,
    filename: Annotated[str, Path(pattern=r"^base-pl\.[1-9][0-9]*\.json\.gz$")],
):
    release_text = filename.split(".")[1]
    if len(release_text) > 10 or int(release_text) > 2147483647:
        raise HTTPException(422)
    try:
        with Session(request.app.state.engine) as session:
            package = session.scalar(
                select(OfflinePackage)
                .join(OfflineChannel, OfflineChannel.package_id == OfflinePackage.package_id)
                .where(
                    OfflinePackage.package_id == OFFICIAL_PACKAGE_ID,
                    OfflinePackage.release == int(release_text),
                    OfflinePackage.state == "published",
                    OfflineChannel.kind == "official",
                )
            )
            if package is None:
                raise HTTPException(404)
            raw = read_published_artifact(
                request.app.state.catalog_artifact_root, package, "official"
            )
            return Response(
                raw, media_type="application/gzip", headers={"ETag": f'"{package.sha256}"'}
            )
    except (SQLAlchemyError, OSError, CatalogValidationError):
        raise _unavailable() from None
