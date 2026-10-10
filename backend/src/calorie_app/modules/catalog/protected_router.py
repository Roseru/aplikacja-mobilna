"""OIDC protected reads of the already published official catalog."""

import unicodedata
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from calorie_app.core.errors import ApiError, DomainError
from calorie_app.integrations.keycloak import Principal
from calorie_app.modules.catalog import OFFICIAL_PACKAGE_ID
from calorie_app.modules.catalog.models import (
    OfflineChannel,
    OfflinePackage,
    OfflinePackageProduct,
    ProductVersion,
)
from calorie_app.modules.catalog.pagination import PAGE_TTL, CursorNotConfigured, database_now
from calorie_app.modules.catalog.product_pages import decode_page, encode_page, expiry_integer
from calorie_app.modules.catalog.repository import active_package, product_data, read_package
from calorie_app.modules.catalog.schemas import ProductDTO, ProductPage, Uuid
from calorie_app.modules.catalog.validation import CatalogValidationError
from calorie_app.modules.identity.dependencies import current_principal
from calorie_app.modules.identity.service import current_epoch, require_account

router = APIRouter(prefix="/api/v1", tags=["catalog"])
ERRORS = {status: {"model": ApiError} for status in (401, 403, 404, 410, 422, 503)}


class ProductQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str | None = Field(default=None, min_length=1, max_length=100)
    limit: int = Field(default=100, ge=1, le=500)
    page_token: str | None = Field(default=None, min_length=1, max_length=4096)


class ProductRevisionQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int | None = Field(default=None, ge=1, le=2147483647)


def _normalized(value):
    return unicodedata.normalize("NFKC", value).casefold()


@router.get(
    "/products",
    response_model=ProductPage,
    operation_id="list_products",
    responses=ERRORS,
    description="Chroniony katalog official po bootstrapie. Strony przypinają niezmienny release, "
    "konto, generację, epokę i parametry przez 60 minut bez przedłużania. "
    "Brak official daje pustą listę.",
)
def list_products(
    request: Request,
    query: Annotated[ProductQuery, Query()],
    principal: Annotated[Principal, Depends(current_principal)],
):
    try:
        with Session(request.app.state.engine) as session, session.begin():
            account = require_account(session, principal)
            epoch = current_epoch(session)
            now = database_now(session)
            after = None
            if query.page_token is None:
                package = active_package(session, OFFICIAL_PACKAGE_ID)
                if package is None:
                    return {"items": [], "next_page_token": None}
                release = package.release
                expiry = expiry_integer(now + PAGE_TTL)
            else:
                token = decode_page(
                    query.page_token,
                    request.app.state.catalog_page_token_secret,
                    owner=account.id,
                    generation=account.generation,
                    epoch=epoch,
                    query=query.query,
                    limit=query.limit,
                    now=now,
                )
                release, expiry, after = token["release"], token["expiry"], token["after"]
                package = session.get(OfflinePackage, (OFFICIAL_PACKAGE_ID, release))
                if package is None or package.state != "published":
                    raise DomainError(404, "not_found")
            latest = {}
            for product in read_package(session, OFFICIAL_PACKAGE_ID, release)["products"]:
                latest[product["product_id"]] = product
            needle = None if query.query is None else _normalized(query.query)
            products = [
                p
                for p in latest.values()
                if (after is None or p["product_id"] > after)
                and (
                    needle is None
                    or any(
                        needle in _normalized(v)
                        for v in [p["name"], *p["aliases"], p["brand"], p["variant"]]
                        if v is not None
                    )
                )
            ]
            products.sort(key=lambda p: p["product_id"])
            page = products[: query.limit]
            next_token = None
            if len(products) > query.limit:
                next_token = encode_page(
                    {
                        "owner": str(account.id),
                        "generation": account.generation,
                        "epoch": str(epoch),
                        "query": query.query,
                        "limit": query.limit,
                        "release": release,
                        "after": page[-1]["product_id"],
                        "expiry": expiry,
                    },
                    request.app.state.catalog_page_token_secret,
                )
            return {"items": page, "next_page_token": next_token}
    except (SQLAlchemyError, CatalogValidationError, CursorNotConfigured):
        raise DomainError(503, "service_unavailable") from None


@router.get(
    "/products/{id}",
    response_model=ProductDTO,
    operation_id="read_product",
    responses=ERRORS,
    description="Chroniony odczyt po bootstrapie. Bez revision najnowsza aktywna wersja official. "
    "Z revision dokładna wersja opublikowanego release official. Niedostępna wersja daje 404.",
)
def read_product(
    request: Request,
    id: Uuid,
    query: Annotated[ProductRevisionQuery, Query()],
    principal: Annotated[Principal, Depends(current_principal)],
):
    try:
        with Session(request.app.state.engine) as session, session.begin():
            require_account(session, principal)
            statement = (
                select(ProductVersion)
                .join(
                    OfflinePackageProduct,
                    and_(
                        OfflinePackageProduct.product_id == ProductVersion.product_id,
                        OfflinePackageProduct.product_revision == ProductVersion.revision,
                    ),
                )
                .join(
                    OfflinePackage,
                    and_(
                        OfflinePackage.package_id == OfflinePackageProduct.package_id,
                        OfflinePackage.release == OfflinePackageProduct.release,
                    ),
                )
                .join(OfflineChannel, OfflineChannel.package_id == OfflinePackage.package_id)
                .where(
                    OfflineChannel.package_id == OFFICIAL_PACKAGE_ID,
                    OfflineChannel.kind == "official",
                    OfflinePackage.state == "published",
                    ProductVersion.product_id == id,
                )
            )
            if query.revision is None:
                statement = statement.where(OfflinePackage.release == OfflineChannel.active_release)
            else:
                statement = statement.where(ProductVersion.revision == query.revision)
            row = session.scalar(statement.order_by(ProductVersion.revision.desc()).limit(1))
            if row is None:
                raise DomainError(404, "not_found")
            return product_data(row)
    except (SQLAlchemyError, CatalogValidationError):
        raise DomainError(503, "service_unavailable") from None
