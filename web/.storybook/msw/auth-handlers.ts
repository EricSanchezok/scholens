import { delay, http, HttpResponse } from "msw";

const api = "http://127.0.0.1:7301/api/v1";
const profileAvatar =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' fill='%23272b35'/%3E%3Ccircle cx='32' cy='25' r='13' fill='%23d9b08c'/%3E%3Cpath d='M10 64c2-17 10-25 22-25s20 8 22 25' fill='%2386a8e7'/%3E%3C/svg%3E";
const error = (code: string, status: number, message = code) =>
  HttpResponse.json(
    {
      code,
      message,
      kind: status >= 500 ? "unavailable" : "unauthenticated",
      retryable: status === 429 || status >= 500,
    },
    { status },
  );

export const actor = {
  id: 7,
  email: "eric@scholens.ai",
  email_verified: true,
  is_active: true,
  is_admin: false,
  is_blocked: false,
  status: "active",
  display_name: "Eric",
  locale: "en",
};

export const authHandlers = {
  lifecycleSuccess: [
    http.post(`${api}/auth/register`, () =>
      HttpResponse.json({
        message: "If the address can receive mail, check your inbox.",
      }),
    ),
    http.post(`${api}/auth/resend-verification`, () =>
      HttpResponse.json({
        message: "If the address can receive mail, check your inbox.",
      }),
    ),
    http.post(`${api}/auth/forgot-password`, () =>
      HttpResponse.json({
        message: "If the address can receive mail, check your inbox.",
      }),
    ),
    http.post(`${api}/auth/verify-email`, () =>
      HttpResponse.json({ message: "Email verified." }),
    ),
    http.post(`${api}/auth/reset-password`, () =>
      HttpResponse.json({ message: "Password reset." }),
    ),
  ],
  success: [
    http.post(`${api}/auth/login`, () =>
      HttpResponse.json({
        access_token: "storybook-access",
        token_type: "bearer",
      }),
    ),
    http.post(`${api}/auth/refresh`, () =>
      HttpResponse.json({
        access_token: "storybook-access",
        token_type: "bearer",
      }),
    ),
    http.post(`${api}/auth/bootstrap`, () =>
      HttpResponse.json({
        access_token: "storybook-access",
        actor,
        token_type: "bearer",
      }),
    ),
    http.get(`${api}/me`, () => HttpResponse.json(actor)),
    http.get(`${api}/me/avatar`, () =>
      HttpResponse.json({
        expires_at: "2026-08-21T10:15:00Z",
        url: profileAvatar,
        version: "11111111-1111-1111-1111-111111111111",
      }),
    ),
    http.post(`${api}/auth/logout`, () => HttpResponse.json({ message: "ok" })),
  ],
  invalidCredentials: [
    http.post(`${api}/auth/login`, () =>
      error("auth_invalid_credentials", 401),
    ),
  ],
  rateLimited: [
    http.post(`${api}/auth/login`, () =>
      HttpResponse.json(
        {
          code: "auth_rate_limited",
          message: "rate limited",
          kind: "rate_limited",
          retryable: true,
        },
        { status: 429, headers: { "Retry-After": "60" } },
      ),
    ),
  ],
  serviceUnavailableLogin: [
    http.post(`${api}/auth/login`, () =>
      error("auth_service_unavailable", 503),
    ),
  ],
  verificationExpired: [
    http.post(`${api}/auth/verify-email`, () =>
      error("auth_verification_token_invalid", 400),
    ),
  ],
  resetExpired: [
    http.post(`${api}/auth/reset-password`, () =>
      error("auth_reset_token_invalid", 400),
    ),
  ],
  refreshMissing: [
    http.post(`${api}/auth/bootstrap`, () =>
      error("auth_session_missing", 401),
    ),
  ],
  refreshExpired: [
    http.post(`${api}/auth/bootstrap`, () =>
      error("auth_session_expired", 401),
    ),
  ],
  refreshReuse: [
    http.post(`${api}/auth/bootstrap`, () =>
      error("auth_session_expired", 401),
    ),
  ],
  unavailable: [
    http.post(`${api}/auth/bootstrap`, () =>
      error("auth_service_unavailable", 503),
    ),
  ],
  offline: [http.post(`${api}/auth/bootstrap`, () => HttpResponse.error())],
  slow: [
    http.post(`${api}/auth/bootstrap`, async () => {
      await delay(1_800);
      return HttpResponse.json({
        access_token: "storybook-access",
        actor,
        token_type: "bearer",
      });
    }),
  ],
  bootstrapping: [
    http.post(`${api}/auth/bootstrap`, async () => {
      await delay(300);
      return HttpResponse.json({
        access_token: "storybook-access",
        actor,
        token_type: "bearer",
      });
    }),
  ],
};
