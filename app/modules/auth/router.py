from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses import ApiResponse
from app.core.database import get_db
from app.modules.auth.dto import (
    AuthSessionDTO,
    ForgotPasswordRequestDTO,
    LoginRequestDTO,
    MessageDTO,
    RefreshTokenRequestDTO,
    ResetPasswordRequestDTO,
    SignUpRequestDTO,
    TokenPairDTO,
    UsernameAvailabilityResponseDTO,
    UsernameSuggestionsResponseDTO,
)
from app.modules.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/signup",
    response_model=ApiResponse[AuthSessionDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Create a new account",
)
async def sign_up(payload: SignUpRequestDTO, db: AsyncSession = Depends(get_db)) -> ApiResponse[AuthSessionDTO]:
    session_data = await AuthService(db).sign_up(payload)
    return ApiResponse(message="Account created successfully", data=session_data)


@router.post("/login", response_model=ApiResponse[AuthSessionDTO], summary="Log in with email/username and password")
async def login(payload: LoginRequestDTO, db: AsyncSession = Depends(get_db)) -> ApiResponse[AuthSessionDTO]:
    session_data = await AuthService(db).login(payload)
    return ApiResponse(message="Login successful", data=session_data)


@router.post("/refresh-token", response_model=ApiResponse[TokenPairDTO], summary="Exchange a refresh token for a new token pair")
async def refresh_token(
    payload: RefreshTokenRequestDTO, db: AsyncSession = Depends(get_db)
) -> ApiResponse[TokenPairDTO]:
    tokens = await AuthService(db).refresh(payload)
    return ApiResponse(message="Token refreshed successfully", data=tokens)


@router.post("/forgot-password", response_model=ApiResponse[MessageDTO], summary="Request a password reset email")
async def forgot_password(
    payload: ForgotPasswordRequestDTO, db: AsyncSession = Depends(get_db)
) -> ApiResponse[MessageDTO]:
    await AuthService(db).forgot_password(payload)
    return ApiResponse(
        message="If an account with that email exists, a password reset link has been sent",
        data=MessageDTO(message="Password reset email sent if the account exists"),
    )


@router.post("/reset-password", response_model=ApiResponse[MessageDTO], summary="Reset password using an emailed token")
async def reset_password(
    payload: ResetPasswordRequestDTO, db: AsyncSession = Depends(get_db)
) -> ApiResponse[MessageDTO]:
    await AuthService(db).reset_password(payload)
    return ApiResponse(
        message="Password reset successfully",
        data=MessageDTO(message="Your password has been updated. Please log in again."),
    )


@router.get(
    "/username/suggestions",
    response_model=ApiResponse[UsernameSuggestionsResponseDTO],
    summary="Generate available username suggestions from a first/last name",
)
async def suggest_usernames(
    first_name: str = Query(..., min_length=1, max_length=100),
    last_name: str = Query(..., min_length=1, max_length=100),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[UsernameSuggestionsResponseDTO]:
    suggestions = await AuthService(db).get_username_suggestions(first_name, last_name)
    return ApiResponse(
        message="Username suggestions generated",
        data=UsernameSuggestionsResponseDTO(suggestions=suggestions),
    )


@router.get(
    "/username/availability",
    response_model=ApiResponse[UsernameAvailabilityResponseDTO],
    summary="Check whether a username is available",
)
async def check_username_availability(
    username: str = Query(..., min_length=3, max_length=30),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[UsernameAvailabilityResponseDTO]:
    available = await AuthService(db).check_username_availability(username.lower())
    return ApiResponse(
        message="Username availability checked",
        data=UsernameAvailabilityResponseDTO(username=username.lower(), available=available),
    )
