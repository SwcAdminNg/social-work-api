from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api_route import NoNullAPIRoute
from app.common.responses import ApiResponse
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.dto import (
    AuthSessionDTO,
    ForgotPasswordRequestDTO,
    LoginRequestDTO,
    LoginResponseDTO,
    MessageDTO,
    RefreshTokenRequestDTO,
    ResetPasswordRequestDTO,
    SignUpRequestDTO,
    TokenPairDTO,
    TwoFactorConfirmCodeRequestDTO,
    TwoFactorLoginResendRequestDTO,
    TwoFactorLoginVerifyRequestDTO,
    TwoFactorSetupChallengeRequestDTO,
    TwoFactorSetupConfirmRequestDTO,
    TwoFactorStatusDTO,
    TwoFactorTotpSetupResponseDTO,
    UsernameAvailabilityResponseDTO,
    UsernameSuggestionsResponseDTO,
)
from app.modules.auth.service import AuthService
from app.modules.user.entity import User

router = APIRouter(prefix="/auth", tags=["Auth"], route_class=NoNullAPIRoute)


@router.post(
    "/signup",
    response_model=ApiResponse[LoginResponseDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Create a new account (2FA setup is required before tokens are issued)",
)
async def sign_up(payload: SignUpRequestDTO, db: AsyncSession = Depends(get_db)) -> ApiResponse[LoginResponseDTO]:
    result = await AuthService(db).sign_up(payload)
    return ApiResponse(message="Account created. Set up two-factor authentication to continue.", data=result)


@router.post(
    "/login",
    response_model=ApiResponse[LoginResponseDTO],
    summary="Log in with email/username and password (2FA setup or verification is required before tokens are issued)",
)
async def login(payload: LoginRequestDTO, db: AsyncSession = Depends(get_db)) -> ApiResponse[LoginResponseDTO]:
    result = await AuthService(db).login(payload)
    message = (
        "Set up two-factor authentication to continue"
        if result.status == "two_factor_setup_required"
        else "Enter your two-factor authentication code to continue"
    )
    return ApiResponse(message=message, data=result)


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


# ---------------------------------------------------------------------------------
# Two-factor authentication — forced setup/verification during signup/login,
# resolved via the short-lived `challenge_token` returned by /signup or /login.
# ---------------------------------------------------------------------------------

@router.post(
    "/2fa/login/verify",
    response_model=ApiResponse[AuthSessionDTO],
    summary="Complete login by verifying a 2FA code (email or authenticator app)",
)
async def verify_login_2fa(
    payload: TwoFactorLoginVerifyRequestDTO, db: AsyncSession = Depends(get_db)
) -> ApiResponse[AuthSessionDTO]:
    session_data = await AuthService(db).verify_login_2fa(payload.challenge_token, payload.code)
    return ApiResponse(message="Login successful", data=session_data)


@router.post(
    "/2fa/login/resend",
    response_model=ApiResponse[MessageDTO],
    summary="Resend the emailed 2FA login code",
)
async def resend_login_2fa_code(
    payload: TwoFactorLoginResendRequestDTO, db: AsyncSession = Depends(get_db)
) -> ApiResponse[MessageDTO]:
    await AuthService(db).resend_login_2fa_code(payload.challenge_token)
    return ApiResponse(message="Verification code resent", data=MessageDTO(message="Code resent"))


@router.post(
    "/2fa/setup/totp/start",
    response_model=ApiResponse[TwoFactorTotpSetupResponseDTO],
    summary="Begin authenticator-app 2FA setup during forced signup/login onboarding",
)
async def start_totp_setup_forced(
    payload: TwoFactorSetupChallengeRequestDTO, db: AsyncSession = Depends(get_db)
) -> ApiResponse[TwoFactorTotpSetupResponseDTO]:
    data = await AuthService(db).start_totp_setup_forced(payload.challenge_token)
    return ApiResponse(message="Scan the QR code or enter the key manually in your authenticator app", data=data)


@router.post(
    "/2fa/setup/totp/confirm",
    response_model=ApiResponse[AuthSessionDTO],
    summary="Confirm authenticator-app 2FA setup and complete signup/login",
)
async def confirm_totp_setup_forced(
    payload: TwoFactorSetupConfirmRequestDTO, db: AsyncSession = Depends(get_db)
) -> ApiResponse[AuthSessionDTO]:
    session_data = await AuthService(db).confirm_totp_setup_forced(payload.challenge_token, payload.code)
    return ApiResponse(message="Two-factor authentication enabled", data=session_data)


@router.post(
    "/2fa/setup/email/start",
    response_model=ApiResponse[MessageDTO],
    summary="Send an email 2FA setup code during forced signup/login onboarding",
)
async def start_email_setup_forced(
    payload: TwoFactorSetupChallengeRequestDTO, db: AsyncSession = Depends(get_db)
) -> ApiResponse[MessageDTO]:
    await AuthService(db).start_email_setup_forced(payload.challenge_token)
    return ApiResponse(message="Verification code sent", data=MessageDTO(message="Code sent"))


@router.post(
    "/2fa/setup/email/confirm",
    response_model=ApiResponse[AuthSessionDTO],
    summary="Confirm email 2FA setup and complete signup/login",
)
async def confirm_email_setup_forced(
    payload: TwoFactorSetupConfirmRequestDTO, db: AsyncSession = Depends(get_db)
) -> ApiResponse[AuthSessionDTO]:
    session_data = await AuthService(db).confirm_email_setup_forced(payload.challenge_token, payload.code)
    return ApiResponse(message="Two-factor authentication enabled", data=session_data)


# ---------------------------------------------------------------------------------
# Two-factor authentication — voluntary switch for an already-logged-in user.
# Referenced from the /users/me profile as the way to change security protocol.
# ---------------------------------------------------------------------------------

@router.get(
    "/2fa/status",
    response_model=ApiResponse[TwoFactorStatusDTO],
    summary="Get the current user's two-factor authentication method",
)
async def get_two_factor_status(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ApiResponse[TwoFactorStatusDTO]:
    data = await AuthService(db).get_two_factor_status(current_user)
    return ApiResponse(message="Two-factor status retrieved", data=data)


@router.post(
    "/2fa/totp/start",
    response_model=ApiResponse[TwoFactorTotpSetupResponseDTO],
    summary="Begin switching to authenticator-app 2FA",
)
async def start_totp_setup(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ApiResponse[TwoFactorTotpSetupResponseDTO]:
    data = await AuthService(db).start_totp_setup(current_user)
    return ApiResponse(message="Scan the QR code or enter the key manually in your authenticator app", data=data)


@router.post(
    "/2fa/totp/confirm",
    response_model=ApiResponse[TwoFactorStatusDTO],
    summary="Confirm switching to authenticator-app 2FA",
)
async def confirm_totp_setup(
    payload: TwoFactorConfirmCodeRequestDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[TwoFactorStatusDTO]:
    data = await AuthService(db).confirm_totp_setup(current_user, payload.code)
    return ApiResponse(message="Switched to authenticator-app 2FA", data=data)


@router.post(
    "/2fa/email/start",
    response_model=ApiResponse[MessageDTO],
    summary="Begin switching to email 2FA",
)
async def start_email_setup(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ApiResponse[MessageDTO]:
    await AuthService(db).start_email_setup(current_user)
    return ApiResponse(message="Verification code sent", data=MessageDTO(message="Code sent"))


@router.post(
    "/2fa/email/confirm",
    response_model=ApiResponse[TwoFactorStatusDTO],
    summary="Confirm switching to email 2FA",
)
async def confirm_email_setup(
    payload: TwoFactorConfirmCodeRequestDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[TwoFactorStatusDTO]:
    data = await AuthService(db).confirm_email_setup(current_user, payload.code)
    return ApiResponse(message="Switched to email 2FA", data=data)
