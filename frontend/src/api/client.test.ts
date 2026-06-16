import {beforeEach, describe, expect, it, vi} from "vitest";

import {
  ApiError,
  clearLocalApiToken,
  createEdge,
  getOntology,
  packContext,
  isLocalApiTokenConfigured,
  request,
  resolveApiUrl,
  retrieveContext,
  setLocalApiToken,
  updateEdge,
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
      "http://localhost:8765/api/context/retrieve",
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
      "http://localhost:8765/api/context/pack",
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

  it("fetches ontology and submits canonical relationship type values", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/ontology")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () =>
            Promise.resolve({
              entity_types: [],
              fact_types: [],
              edge_types: [
                {
                  relation_type: "vendor_contact",
                  description: "Vendor contact",
                  from_entity_type: "person",
                  to_entity_type: "person",
                  directed_default: false,
                },
              ],
              observation_types: [],
              policies: {
                sensitivity_levels: [],
                ai_use_policies: [],
                claim_types: [],
                candidate_types: [],
              },
            }),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({id: "edge-1", ...JSON.parse(String(init?.body ?? "{}"))}),
      } as Response);
    });
    vi.stubGlobal("fetch", fetchMock);

    const ontology = await getOntology();
    await createEdge({
      from_entity_id: "self-1",
      to_entity_id: "person-2",
      relation_type: ontology.edge_types[0].relation_type,
      claim_text: "Dana is the vendor contact.",
      claim_type: "fact",
      created_by: "user",
    });
    await updateEdge("edge-1", {relation_type: ontology.edge_types[0].relation_type});

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://localhost:8765/api/ontology",
      expect.any(Object),
    );
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toMatchObject({
      relation_type: "vendor_contact",
    });
    expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body))).toMatchObject({
      relation_type: "vendor_contact",
    });
  });
});
