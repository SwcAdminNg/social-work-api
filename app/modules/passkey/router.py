import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api_route import NoNullAPIRoute
from app.common.pagination import PaginatedResponse, PaginationParams
from app.common.responses import ApiResponse
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_admin_user, get_current_user
from app.modules.auth.dto import AuthSessionDTO
from app.modules.passkey.dto import (
    AdminPasskeyFilterParams,
    AdminPasskeyReadDTO,
    PasskeyLoginOptionsRequestDTO,
    PasskeyLoginVerifyRequestDTO,
    PasskeyOptionsResponseDTO,
    PasskeyOwnerDTO,
    PasskeyReadDTO,
    PasskeyRegistrationOptionsRequestDTO,
    PasskeyRegistrationVerifyRequestDTO,
    PasskeyRenameRequestDTO,
)
from app.modules.passkey.service import PasskeyService
from app.modules.user.entity import User

router = APIRouter(prefix="/auth/passkeys", tags=["Passkeys"], route_class=NoNullAPIRoute)
admin_router = APIRouter(prefix="/admin/passkeys", tags=["Admin Passkeys"], route_class=NoNullAPIRoute)


def _user_agent(request: Request) -> str | None:
    # The website's server forwards the visitor's browser as X-Client-User-Agent.
    return request.headers.get("x-client-user-agent") or request.headers.get("user-agent")


# -- sign-in (public) ----------------------------------------------------------


@router.post("/login/options", response_model=ApiResponse[PasskeyOptionsResponseDTO], summary="Start a passkey sign-in")
async def passkey_login_options(
    payload: PasskeyLoginOptionsRequestDTO, db: AsyncSession = Depends(get_db)
) -> ApiResponse[PasskeyOptionsResponseDTO]:
    data = await PasskeyService(db).start_login(payload.origin, payload.identifier)
    return ApiResponse(message="Passkey sign-in started", data=PasskeyOptionsResponseDTO(**data))


@router.post("/login/verify", response_model=ApiResponse[AuthSessionDTO], summary="Finish a passkey sign-in")
async def passkey_login_verify(
    payload: PasskeyLoginVerifyRequestDTO, request: Request, db: AsyncSession = Depends(get_db)
) -> ApiResponse[AuthSessionDTO]:
    session_data = await PasskeyService(db).finish_login(
        payload.origin, payload.challenge_token, payload.credential, payload.keep_logged_in, _user_agent(request)
    )
    return ApiResponse(message="Login successful", data=session_data)


# -- the signed-in user's own passkeys -----------------------------------------


@router.get("", response_model=ApiResponse[list[PasskeyReadDTO]], summary="List my passkeys")
async def list_my_passkeys(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ApiResponse[list[PasskeyReadDTO]]:
    passkeys = await PasskeyService(db).list_for_user(current_user.id)
    return ApiResponse(message="Passkeys retrieved", data=[PasskeyReadDTO.model_validate(p) for p in passkeys])


@router.post("/register/options", response_model=ApiResponse[PasskeyOptionsResponseDTO], summary="Start adding a passkey")
async def passkey_register_options(
    payload: PasskeyRegistrationOptionsRequestDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PasskeyOptionsResponseDTO]:
    data = await PasskeyService(db).start_registration(current_user, payload.origin)
    return ApiResponse(message="Passkey registration started", data=PasskeyOptionsResponseDTO(**data))


@router.post(
    "/register/verify",
    response_model=ApiResponse[PasskeyReadDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Finish adding a passkey",
)
async def passkey_register_verify(
    payload: PasskeyRegistrationVerifyRequestDTO,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PasskeyReadDTO]:
    passkey = await PasskeyService(db).finish_registration(
        current_user, payload.origin, payload.challenge_token, payload.credential, payload.name, _user_agent(request)
    )
    return ApiResponse(message="Passkey added", data=PasskeyReadDTO.model_validate(passkey))


@router.patch("/{passkey_id}", response_model=ApiResponse[PasskeyReadDTO], summary="Rename one of my passkeys")
async def rename_my_passkey(
    passkey_id: uuid.UUID,
    payload: PasskeyRenameRequestDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PasskeyReadDTO]:
    passkey = await PasskeyService(db).rename(current_user, passkey_id, payload.name)
    return ApiResponse(message="Passkey renamed", data=PasskeyReadDTO.model_validate(passkey))


@router.delete("/{passkey_id}", response_model=ApiResponse[dict], summary="Remove one of my passkeys")
async def delete_my_passkey(
    passkey_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ApiResponse[dict]:
    await PasskeyService(db).delete(current_user, passkey_id)
    return ApiResponse(message="Passkey removed", data={"id": str(passkey_id)})


# -- admin -----------------------------------------------------------------------


@admin_router.get("", response_model=PaginatedResponse[AdminPasskeyReadDTO], summary="List registered passkeys (admin)")
async def admin_list_passkeys(
    pagination: PaginationParams = Depends(),
    filters: AdminPasskeyFilterParams = Depends(),
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[AdminPasskeyReadDTO]:
    rows, total = await PasskeyService(db).admin_list(pagination, filters)
    items = [
        AdminPasskeyReadDTO(
            **PasskeyReadDTO.model_validate(passkey).model_dump(exclude={"provider", "synced"}),
            user=PasskeyOwnerDTO.model_validate(user),
        )
        for passkey, user in rows
    ]
    return PaginatedResponse.create(items=items, total_items=total, params=pagination)


@admin_router.delete("/{passkey_id}", response_model=ApiResponse[dict], summary="Revoke a passkey (admin)")
async def admin_revoke_passkey(
    passkey_id: uuid.UUID, current_admin: User = Depends(get_current_admin_user), db: AsyncSession = Depends(get_db)
) -> ApiResponse[dict]:
    await PasskeyService(db).admin_revoke(passkey_id)
    return ApiResponse(message="Passkey revoked", data={"id": str(passkey_id)})
