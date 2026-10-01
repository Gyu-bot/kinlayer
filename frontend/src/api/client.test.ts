import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  clearLocalApiToken,
  isLocalApiTokenConfigured,
  request,
  resolveApiUrl,
  setLocalApiToken,
} from "./client";

describe("API client", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("sends a locally configured bearer token without exposing the token value", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ ok: true }),
    });
    vi.stubGlobal("fetch", fetchMock);

    setLocalApiToken("local-secret");

    await request("/api/system/config");

    expect(isLocalApiTokenConfigured()).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8765/api/system/config",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer local-secret",
        }),
      }),
    );

    clearLocalApiToken();
    expect(isLocalApiTokenConfigured()).toBe(false);
  });

  it("uses the current web hostname for the default API URL", () => {
    expect(
      resolveApiUrl(undefined, {
        protocol: "http:",
        hostname: "192.168.1.38",
      }),
    ).toBe("http://192.168.1.38:8765");
  });

  it("keeps bracketed IPv6 hostnames valid for the default API URL", () => {
    expect(
      resolveApiUrl(undefined, {
        protocol: "http:",
        hostname: "[::1]",
      }),
    ).toBe("http://[::1]:8765");
  });

  it("keeps an explicitly configured API URL", () => {
    expect(
      resolveApiUrl("http://127.0.0.1:8765", {
        protocol: "http:",
        hostname: "192.168.1.38",
      }),
    ).toBe("http://127.0.0.1:8765");
  });

  it("raises common API errors with status, code, message, and details", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        json: () =>
          Promise.resolve({
            error: {
              code: "validation_error",
              message: "Invalid relationship.",
              details: { relation_type: "unknown" },
            },
          }),
      }),
    );

    await expect(request("/api/edges")).rejects.toMatchObject({
      status: 422,
      code: "validation_error",
      message: "Invalid relationship.",
      details: { relation_type: "unknown" },
    });
    await expect(request("/api/edges")).rejects.toBeInstanceOf(ApiError);
  });
});
