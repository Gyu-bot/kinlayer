import {beforeEach, describe, expect, it, vi} from "vitest";

import {
  ApiError,
  clearLocalApiToken,
  packContext,
  isLocalApiTokenConfigured,
  request,
  retrieveContext,
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
      json: () => Promise.resolve({ok: true}),
    });
    vi.stubGlobal("fetch", fetchMock);

    setLocalApiToken("local-secret");

    await request("/api/system/config");

    expect(isLocalApiTokenConfigured()).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/api/system/config",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer local-secret",
        }),
      }),
    );

    clearLocalApiToken();
    expect(isLocalApiTokenConfigured()).toBe(false);
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
              details: {relation_type: "unknown"},
            },
          }),
      }),
    );

    await expect(request("/api/edges")).rejects.toMatchObject({
      status: 422,
      code: "validation_error",
      message: "Invalid relationship.",
      details: {relation_type: "unknown"},
    });
    await expect(request("/api/edges")).rejects.toBeInstanceOf(ApiError);
  });

  it("calls context retrieve and pack endpoints with debug payloads", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({matched_entities: []}),
    });
    vi.stubGlobal("fetch", fetchMock);

    await retrieveContext({
      query: "민지와 다음 미팅",
      entity_hints: ["person-1"],
      focal_entity_id: "self-1",
      include_debug: true,
      limit: 8,
    });
    await packContext({
      query: "민지와 다음 미팅",
      situation: "follow_up",
      entity_hints: ["person-1"],
      focal_entity_id: "self-1",
      include_debug: true,
      limit: 8,
    });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:8765/api/context/retrieve",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          query: "민지와 다음 미팅",
          entity_hints: ["person-1"],
          focal_entity_id: "self-1",
          include_debug: true,
          limit: 8,
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8765/api/context/pack",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          query: "민지와 다음 미팅",
          situation: "follow_up",
          entity_hints: ["person-1"],
          focal_entity_id: "self-1",
          include_debug: true,
          limit: 8,
        }),
      }),
    );
  });
});
