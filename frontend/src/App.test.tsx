import {cleanup, fireEvent, render, screen, waitFor, within} from "@testing-library/react";
import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";

import App from "./App";

function jsonResponse(payload: unknown) {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(payload),
  } as Response);
}

describe("App route shell", () => {
  beforeEach(() => {
    localStorage.clear();
    window.history.pushState({}, "", "/");
    vi.restoreAllMocks();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("supports the MVP routes from the shell", () => {
    vi.stubGlobal("fetch", vi.fn());

    render(<App />);

    const nav = within(screen.getByRole("navigation", {name: "Primary"}));
    expect(nav.getByRole("button", {name: "People"})).toBeInTheDocument();
    expect(nav.getByRole("button", {name: "New person"})).toBeInTheDocument();
    expect(nav.getByRole("button", {name: "Candidates"})).toBeInTheDocument();
    expect(nav.getByRole("button", {name: "Agent operations"})).toBeInTheDocument();
    expect(nav.getByRole("button", {name: "Graph"})).toBeInTheDocument();
    expect(nav.getByRole("button", {name: "Retrieval debug"})).toBeInTheDocument();
    expect(nav.getByRole("button", {name: "Settings"})).toBeInTheDocument();
  });

  it("renders agent write operations and downloads the current export", async () => {
    window.history.pushState({}, "", "/agent-operations");
    const createObjectUrl = vi.fn(() => "blob:agent-operations");
    const revokeObjectUrl = vi.fn();
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: createObjectUrl,
      revokeObjectURL: revokeObjectUrl,
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith("/api/agent-operations?limit=50")) {
        return jsonResponse({
          items: [
            {
              id: "audit-id",
              operation_type: "candidate_submit",
              source_path: "/api/candidates",
              actor: "ai_agent",
              result_status: "success",
              api_error_code: null,
              request_summary: {candidate_type: "observation"},
              diagnostics: {},
              related_refs: {},
              candidate_id: "candidate-id",
              correction_id: null,
              episode_id: "episode-id",
              canonical_record_ref: null,
              bounded_excerpt: "Alex prefers concise follow-ups.",
              created_at: "2026-06-12T00:00:00Z",
              updated_at: "2026-06-12T00:00:00Z",
            },
          ],
          total: 1,
          limit: 50,
          offset: 0,
        });
      }
      if (url.endsWith("/api/agent-operations/export?limit=200")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          text: () =>
            Promise.resolve(
              '{"record_type":"manifest","schema_version":"agent_write_operations.v1"}\n',
            ),
        } as Response);
      }
      throw new Error(`Unexpected URL ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    await waitFor(() =>
      expect(screen.getByRole("heading", {level: 1, name: "Agent Write Operations"})).toBeInTheDocument(),
    );
    expect(screen.getAllByText("candidate_submit").length).toBeGreaterThan(0);
    expect(screen.getByText("Alex prefers concise follow-ups.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", {name: "Export"}));

    await waitFor(() => expect(createObjectUrl).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[1][0])).toContain("/api/agent-operations/export?limit=200");
    expect(revokeObjectUrl).toHaveBeenCalledWith("blob:agent-operations");
  });

  it("renders settings without exposing the stored local token value", async () => {
    localStorage.setItem("kinlayer.apiToken", "local-secret");
    window.history.pushState({}, "", "/settings");
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url.endsWith("/api/system/health")) {
          return jsonResponse({status: "ok", database: "ok", embedding: "disabled"});
        }
        if (url.endsWith("/api/system/config")) {
          return jsonResponse({
            bind_host: "127.0.0.1",
            auth_token_configured: false,
            embedding: {
              provider: "openai_compatible",
              model: "text-embedding-3-small",
              dim: 1536,
              status: "ready",
              api_url_configured: true,
              api_key_configured: true,
            },
          });
        }
        if (url.endsWith("/api/embeddings/status")) {
          return jsonResponse({
            provider: "openai_compatible",
            model: "text-embedding-3-small",
            dim: 1536,
            status: "ready",
            api_url_configured: true,
            api_key_configured: true,
            observations: {total: 0, pending: 0, failed: 0, embedded: 0},
          });
        }
        if (url.endsWith("/api/ontology")) {
          return jsonResponse({
            entity_types: [{value: "person", label: "Person", support_level: "supported"}],
            fact_types: [{value: "organization", label: "Organization", support_level: "supported"}],
            edge_types: [{relation_type: "client_contact", description: "Client contact"}],
            observation_types: [
              {observation_type: "recent_interaction", description: "Recent interaction"},
            ],
            policies: {
              sensitivity_levels: [{value: "medium", label: "Medium", support_level: "supported"}],
              ai_use_policies: [
                {value: "cautious_use", label: "Cautious use", support_level: "supported"},
              ],
              claim_types: [],
              candidate_types: [],
            },
          });
        }
        throw new Error(`Unexpected URL ${url}`);
      }),
    );

    render(<App />);

    await waitFor(() =>
      expect(screen.getByRole("heading", {level: 1, name: "Settings"})).toBeInTheDocument(),
    );
    expect(screen.getAllByText("http://localhost:8765").length).toBeGreaterThan(0);
    expect(screen.getByText("Local token configured")).toBeInTheDocument();
    expect(screen.getAllByText("openai_compatible").length).toBeGreaterThan(0);
    expect(screen.getAllByText("text-embedding-3-small").length).toBeGreaterThan(0);
    expect(screen.getByText("Embedding API URL")).toBeInTheDocument();
    expect(screen.getByText("Embedding API key")).toBeInTheDocument();
    expect(screen.getByText("Server .env")).toBeInTheDocument();
    expect(screen.getByText("KINLAYER_EMBEDDING_API_KEY")).toBeInTheDocument();
    expect(screen.queryByText("KINLAYER_EMBEDDING_PROVIDER")).not.toBeInTheDocument();
    expect(screen.queryByText("KINLAYER_EMBEDDING_API_URL")).not.toBeInTheDocument();
    expect(screen.queryByText("KINLAYER_EMBEDDING_MODEL")).not.toBeInTheDocument();
    expect(screen.queryByText("KINLAYER_EMBEDDING_DIM")).not.toBeInTheDocument();
    expect(screen.getAllByText("Configured").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("client_contact")).toBeInTheDocument();
    expect(screen.getByText("recent_interaction")).toBeInTheDocument();
    expect(screen.queryByText("local-secret")).not.toBeInTheDocument();
    expect(screen.queryByText("openai-secret")).not.toBeInTheDocument();
  });

  it("renders retrieval debug results with Korean semantic metadata", async () => {
    window.history.pushState({}, "", "/retrieval-debug");
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/context/retrieve")) {
        expect(init?.method).toBe("POST");
        expect(JSON.parse(String(init?.body))).toMatchObject({
          query: "민지와 다음 미팅 전에 확인할 내용",
          entity_hints: ["person-1", "person-2"],
          focal_entity_id: "self-1",
          include_debug: true,
        });
        return jsonResponse({
          matched_entities: [
            {
              entity_id: "person-1",
              display_name: "김민지",
              entity_type: "person",
              score: 0.91,
              confidence_band: "high",
              match_reasons: ["semantic_similarity", "alias_hint"],
              score_breakdown: {semantic: 0.62, lexical: 0.21, recency: 0.08},
              penalties: {},
              surface_bucket: "direct_surface",
              sensitivity: "medium",
              ai_use_policy: "cautious_use",
              confirmation_status: "confirmed",
              observations: [
                {
                  observation_id: "obs-1",
                  content: "민지는 회의 전에 짧은 의제 공유를 선호한다.",
                  score: 0.85,
                  match_reasons: ["semantic_similarity"],
                  sensitivity: "medium",
                  ai_use_policy: "cautious_use",
                  status: "active",
                },
              ],
            },
          ],
          observations: [],
          scores: {"person-1": 0.91},
          match_reasons: {"person-1": ["semantic_similarity", "alias_hint"]},
          score_breakdown: {"person-1": {semantic: 0.62, lexical: 0.21}},
          ambiguity_detected: false,
          debug: {embedding_provider: "local", score_weights: {semantic: 0.55}},
        });
      }
      if (url.endsWith("/api/context/pack")) {
        expect(init?.method).toBe("POST");
        expect(JSON.parse(String(init?.body))).toMatchObject({
          query: "민지와 다음 미팅 전에 확인할 내용",
          situation: "follow_up",
          entity_hints: ["person-1", "person-2"],
          focal_entity_id: "self-1",
          include_debug: true,
        });
        return jsonResponse({
          context_pack: {
            confidence: "high",
            suggested_response_policy: "conditional_use",
            ambiguity_detected: false,
            matched_entities: [],
            buckets: {
              direct_surface: [
                {
                  entity_id: "person-1",
                  display_name: "김민지",
                  entity_type: "person",
                  score: 0.91,
                  confidence_band: "high",
                  match_reasons: ["semantic_similarity"],
                  score_breakdown: {semantic: 0.62},
                  penalties: {},
                  surface_bucket: "direct_surface",
                  sensitivity: "medium",
                  ai_use_policy: "cautious_use",
                  confirmation_status: "confirmed",
                  observations: [],
                },
              ],
              conditional_surface: [],
              internal_only: [],
              blocked: [],
            },
            recent_context: [
              {
                observation_id: "obs-1",
                content: "민지는 회의 전에 짧은 의제 공유를 선호한다.",
                score: 0.85,
                match_reasons: ["semantic_similarity"],
                sensitivity: "medium",
                ai_use_policy: "cautious_use",
                status: "active",
              },
            ],
            stable_context: [],
            cautions: [],
            provenance: [],
          },
          debug: {packing: "policy_bucketed"},
        });
      }
      throw new Error(`Unexpected URL ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    fireEvent.change(screen.getByLabelText("Query"), {
      target: {value: "민지와 다음 미팅 전에 확인할 내용"},
    });
    fireEvent.change(screen.getByLabelText("Situation"), {target: {value: "follow_up"}});
    fireEvent.change(screen.getByLabelText("Focal entity ID"), {target: {value: "self-1"}});
    fireEvent.change(screen.getByLabelText("Candidate entity IDs"), {
      target: {value: "person-1, person-2"},
    });
    fireEvent.click(screen.getByRole("button", {name: "Run debug"}));

    await waitFor(() => expect(screen.getAllByText("김민지").length).toBeGreaterThan(0));
    expect(
      screen.getAllByText("민지는 회의 전에 짧은 의제 공유를 선호한다.").length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByText("direct_surface").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/semantic_similarity/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/\"semantic\": 0.62/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/\"embedding_provider\": \"local\"/).length).toBeGreaterThan(0);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("creates a person with optional relationship and observation bootstrap", async () => {
    window.history.pushState({}, "", "/people/new");
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/entities?entity_type=person&system_role=self&limit=1")) {
        return jsonResponse({
          items: [entityFixture({id: "self-1", display_name: "Me", system_role: "self"})],
          limit: 1,
          offset: 0,
          total: 1,
        });
      }
      if (url.endsWith("/api/entities") && init?.method === "POST") {
        return jsonResponse(entityFixture({id: "person-new", display_name: "박서연"}));
      }
      if (url.endsWith("/api/edges") && init?.method === "POST") {
        return jsonResponse({id: "edge-1", ...JSON.parse(String(init.body))});
      }
      if (url.endsWith("/api/observations") && init?.method === "POST") {
        return jsonResponse({id: "obs-1", embedding_status: "pending", ...JSON.parse(String(init.body))});
      }
      if (url.endsWith("/api/entities/person-new")) {
        return jsonResponse(entityFixture({id: "person-new", display_name: "박서연"}));
      }
      if (url.endsWith("/api/entities/person-new/aliases")) {
        return jsonResponse({items: [], limit: 200, offset: 0, total: 0});
      }
      if (url.includes("/api/entity-facts?")) {
        return jsonResponse({items: [], limit: 100, offset: 0, total: 0});
      }
      if (url.endsWith("/api/entities/person-new/context-card")) {
        return jsonResponse(contextCardFixture({entity: entityFixture({id: "person-new", display_name: "박서연"})}));
      }
      throw new Error(`Unexpected URL ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    fireEvent.change(screen.getByLabelText("Display name"), {target: {value: "박서연"}});
    fireEvent.change(screen.getByLabelText("Initial relationship type"), {
      target: {value: "friend"},
    });
    fireEvent.change(screen.getByLabelText("Initial relationship note"), {
      target: {value: "서연은 사용자와 오래 알고 지낸 친구다."},
    });
    fireEvent.change(screen.getByLabelText("Initial observation type"), {
      target: {value: "recent_interaction"},
    });
    fireEvent.change(screen.getByLabelText("Initial observation"), {
      target: {value: "서연은 다음 만남 전에 짧은 확인 메시지를 선호한다."},
    });
    fireEvent.click(screen.getByRole("button", {name: "Create person"}));

    await waitFor(() =>
      expect(screen.getByRole("heading", {level: 1, name: "박서연"})).toBeInTheDocument(),
    );
    const edgeCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/api/edges"));
    const observationCall = fetchMock.mock.calls.find(([url]) =>
      String(url).endsWith("/api/observations"),
    );
    expect(JSON.parse(String(edgeCall?.[1]?.body))).toMatchObject({
      from_entity_id: "self-1",
      to_entity_id: "person-new",
      relation_type: "friend",
      claim_text: "서연은 사용자와 오래 알고 지낸 친구다.",
    });
    expect(JSON.parse(String(observationCall?.[1]?.body))).toMatchObject({
      subject_entity_id: "person-new",
      observation_type: "recent_interaction",
      content: "서연은 다음 만남 전에 짧은 확인 메시지를 선호한다.",
      related_entities: [{entity_id: "self-1", role: "related"}],
    });
  });

  it("shows relationship, observation, and provenance context on person detail", async () => {
    window.history.pushState({}, "", "/people/person-1");
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url.endsWith("/api/entities/person-1")) {
          return jsonResponse(entityFixture({id: "person-1", display_name: "김민지"}));
        }
        if (url.endsWith("/api/entities/person-1/aliases")) {
          return jsonResponse({items: [], limit: 200, offset: 0, total: 0});
        }
        if (url.includes("/api/entity-facts?")) {
          return jsonResponse({
            items: [
              {
                id: "fact-1",
                entity_id: "person-1",
                fact_type: "organization",
                content: "Kinlayer Labs",
                claim_type: "fact",
                confidence: 1,
                sensitivity: "medium",
                ai_use_policy: "cautious_use",
                status: "active",
                created_by: "user",
                created_at: "2026-06-10T00:00:00Z",
                updated_at: "2026-06-10T00:00:00Z",
              },
            ],
            limit: 100,
            offset: 0,
            total: 1,
          });
        }
        if (url.endsWith("/api/entities/person-1/context-card")) {
          return jsonResponse(
            contextCardFixture({
              entity: entityFixture({id: "person-1", display_name: "김민지"}),
              relationship_edges: [
                {
                  id: "edge-1",
                  from_entity_id: "self-1",
                  to_entity_id: "person-1",
                  relation_type: "friend",
                  directed: false,
                  claim_text: "민지는 사용자와 오래 알고 지낸 친구다.",
                  claim_type: "fact",
                  properties: {},
                  confidence: 0.9,
                  status: "active",
                  valid_from: null,
                  valid_to: null,
                  sensitivity: "medium",
                  ai_use_policy: "cautious_use",
                  created_by: "user",
                  invalidated_by_edge_id: null,
                  source_candidate_id: null,
                  first_seen_at: null,
                  last_seen_at: null,
                  created_at: "2026-06-10T00:00:00Z",
                  updated_at: "2026-06-10T00:00:00Z",
                },
              ],
              stable_context: [
                observationFixture({
                  id: "obs-stable",
                  content: "민지는 긴 설명보다 핵심 요약을 선호한다.",
                  observation_type: "communication_preference",
                }),
              ],
              recent_context: [
                observationFixture({
                  id: "obs-recent",
                  content: "최근 프로젝트 킥오프에 대해 후속 확인이 필요하다.",
                  observation_type: "recent_interaction",
                }),
              ],
              provenance_summary: {
                fact_count: 1,
                edge_count: 1,
                observation_count: 2,
                evidence_count: 3,
                evidence: [
                  {
                    record_type: "edge",
                    record_id: "edge-1",
                    episode_id: "episode-1",
                    excerpt: "오래 알고 지낸 친구",
                    confidence: 0.9,
                    created_at: "2026-06-10T00:00:00Z",
                  },
                ],
              },
            }),
          );
        }
        throw new Error(`Unexpected URL ${url}`);
      }),
    );

    render(<App />);

    await waitFor(() =>
      expect(screen.getByRole("heading", {level: 1, name: "김민지"})).toBeInTheDocument(),
    );
    expect(screen.getByLabelText("Relationship type edge-1")).toHaveValue("friend");
    expect(screen.getByLabelText("Relationship claim edge-1")).toHaveValue(
      "민지는 사용자와 오래 알고 지낸 친구다.",
    );
    expect(screen.getByText("민지는 긴 설명보다 핵심 요약을 선호한다.")).toBeInTheDocument();
    expect(screen.getByText("최근 프로젝트 킥오프에 대해 후속 확인이 필요하다.")).toBeInTheDocument();
    expect(screen.getByText("Facts 1 / Edges 1 / Observations 2 / Evidence 3")).toBeInTheDocument();
    expect(screen.getByText("오래 알고 지낸 친구")).toBeInTheDocument();
  });

  it("edits person profile records through canonical APIs and refreshes context", async () => {
    window.history.pushState({}, "", "/people/person-1");
    let person = entityFixture({
      id: "person-1",
      display_name: "김민지",
      properties: {short_note: "초기 메모"},
    });
    let aliases = [
      {
        id: "alias-1",
        entity_id: "person-1",
        alias: "민지",
        normalized_alias: "민지",
        status: "active",
        confidence: 1,
        created_by: "user",
        created_at: "2026-06-10T00:00:00Z",
        updated_at: "2026-06-10T00:00:00Z",
      },
    ];
    let facts = [
      {
        id: "fact-1",
        entity_id: "person-1",
        fact_type: "email",
        content: "old@example.com",
        value: {kind: "work", email: "old@example.com"},
        claim_type: "fact",
        confidence: 1,
        sensitivity: "medium",
        ai_use_policy: "cautious_use",
        status: "active",
        created_by: "user",
        created_at: "2026-06-10T00:00:00Z",
        updated_at: "2026-06-10T00:00:00Z",
      },
    ];
    let edges = [
      {
        id: "edge-1",
        from_entity_id: "self-1",
        to_entity_id: "person-1",
        relation_type: "friend",
        directed: false,
        claim_text: "오랜 친구",
        claim_type: "fact",
        properties: {},
        confidence: 1,
        status: "active",
        valid_from: null,
        valid_to: null,
        sensitivity: "medium",
        ai_use_policy: "cautious_use",
        created_by: "user",
        invalidated_by_edge_id: null,
        source_candidate_id: null,
        first_seen_at: null,
        last_seen_at: null,
        created_at: "2026-06-10T00:00:00Z",
        updated_at: "2026-06-10T00:00:00Z",
      },
    ];
    let observations = [observationFixture({id: "obs-1", content: "삭제할 관찰"})];
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(String(init.body)) : {};
      if (url.endsWith("/api/entities/person-1") && !init?.method) {
        return jsonResponse(person);
      }
      if (url.endsWith("/api/entities/person-1") && init?.method === "PATCH") {
        person = {...person, ...body, properties: body.properties};
        return jsonResponse(person);
      }
      if (url.endsWith("/api/entities/person-1/aliases") && !init?.method) {
        return jsonResponse({items: aliases, limit: 200, offset: 0, total: aliases.length});
      }
      if (url.endsWith("/api/entities/person-1/aliases") && init?.method === "POST") {
        aliases = [{...aliases[0], id: "alias-2", alias: body.alias}, ...aliases];
        return jsonResponse(aliases[0]);
      }
      if (url.endsWith("/api/aliases/alias-1") && init?.method === "PATCH") {
        aliases = aliases.map((alias) => (alias.id === "alias-1" ? {...alias, ...body} : alias));
        return jsonResponse(aliases.find((alias) => alias.id === "alias-1"));
      }
      if (url.endsWith("/api/aliases/alias-1") && init?.method === "DELETE") {
        aliases = aliases.filter((alias) => alias.id !== "alias-1");
        return jsonResponse({...aliases[0], id: "alias-1", status: "deleted"});
      }
      if (url.includes("/api/entity-facts?")) {
        return jsonResponse({items: facts, limit: 100, offset: 0, total: facts.length});
      }
      if (url.endsWith("/api/entity-facts") && init?.method === "POST") {
        facts = [{id: "fact-2", created_at: "2026-06-10T00:00:00Z", updated_at: "2026-06-10T00:00:00Z", ...body}, ...facts];
        return jsonResponse(facts[0]);
      }
      if (url.endsWith("/api/entity-facts/fact-1") && init?.method === "PATCH") {
        facts = facts.map((fact) => (fact.id === "fact-1" ? {...fact, ...body} : fact));
        return jsonResponse(facts.find((fact) => fact.id === "fact-1"));
      }
      if (url.endsWith("/api/entity-facts/fact-1") && init?.method === "DELETE") {
        facts = facts.filter((fact) => fact.id !== "fact-1");
        return jsonResponse({id: "fact-1", status: "deleted"});
      }
      if (url.endsWith("/api/edges") && init?.method === "POST") {
        edges = [{id: "edge-2", status: "active", confidence: 1, ...body}, ...edges];
        return jsonResponse(edges[0]);
      }
      if (url.endsWith("/api/edges/edge-1") && init?.method === "PATCH") {
        edges = edges.map((edge) => (edge.id === "edge-1" ? {...edge, ...body} : edge));
        return jsonResponse(edges.find((edge) => edge.id === "edge-1"));
      }
      if (url.endsWith("/api/edges/edge-1") && init?.method === "DELETE") {
        edges = edges.filter((edge) => edge.id !== "edge-1");
        return jsonResponse({id: "edge-1", status: "deleted"});
      }
      if (url.endsWith("/api/observations/obs-1") && init?.method === "DELETE") {
        observations = [];
        return jsonResponse(observationFixture({id: "obs-1", status: "deleted"}));
      }
      if (url.endsWith("/api/entities/person-1/context-card")) {
        return jsonResponse(
          contextCardFixture({
            entity: person,
            aliases,
            profile_facts: facts,
            relationship_edges: edges,
            recent_context: observations,
          }),
        );
      }
      throw new Error(`Unexpected URL ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    await waitFor(() =>
      expect(screen.getByRole("heading", {level: 1, name: "김민지"})).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText("Display name"), {target: {value: "김민지 수정"}});
    fireEvent.change(screen.getByLabelText("Profile note"), {target: {value: "새 메모"}});
    fireEvent.click(screen.getByRole("button", {name: "Save profile"}));
    await waitFor(() => expect(screen.getByRole("heading", {level: 1, name: "김민지 수정"})).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("New alias"), {target: {value: "MJ"}});
    fireEvent.click(screen.getByRole("button", {name: "Add alias"}));
    await waitFor(() => expect(screen.getByDisplayValue("MJ")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Alias alias-1"), {target: {value: "민지님"}});
    fireEvent.click(screen.getByRole("button", {name: "Update alias alias-1"}));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/api/aliases/alias-1"))).toBe(true));

    fireEvent.change(screen.getByLabelText("New structured fact content"), {
      target: {value: "new@example.com"},
    });
    fireEvent.click(screen.getByRole("button", {name: "Add structured fact"}));
    await waitFor(() => expect(screen.getByDisplayValue("new@example.com")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Fact content fact-1"), {
      target: {value: "updated@example.com"},
    });
    fireEvent.click(screen.getByRole("button", {name: "Update fact fact-1"}));

    fireEvent.change(screen.getByLabelText("Related entity ID"), {target: {value: "person-2"}});
    fireEvent.change(screen.getByLabelText("Relationship note"), {target: {value: "협업 파트너"}});
    fireEvent.click(screen.getByRole("button", {name: "Add relationship"}));
    await waitFor(() => expect(screen.getByDisplayValue("협업 파트너")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Relationship claim edge-1"), {target: {value: "가까운 친구"}});
    fireEvent.click(screen.getByRole("button", {name: "Update relationship edge-1"}));

    fireEvent.click(screen.getByRole("button", {name: "Delete observation obs-1"}));
    await waitFor(() => expect(screen.queryByText("삭제할 관찰")).not.toBeInTheDocument());

    expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith("/api/entities/person-1") && init?.method === "PATCH")).toBe(true);
    expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith("/api/entity-facts/fact-1") && init?.method === "PATCH")).toBe(true);
    expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith("/api/edges/edge-1") && init?.method === "PATCH")).toBe(true);
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/api/entities/person-1/context-card"))).toBe(true);
  });

  it("shows validation errors while keeping the person detail form open", async () => {
    window.history.pushState({}, "", "/people/person-1");
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith("/api/entities/person-1") && !init?.method) {
          return jsonResponse(entityFixture({id: "person-1", display_name: "김민지"}));
        }
        if (url.endsWith("/api/entities/person-1/aliases")) {
          return jsonResponse({items: [], limit: 200, offset: 0, total: 0});
        }
        if (url.includes("/api/entity-facts?")) {
          return jsonResponse({items: [], limit: 100, offset: 0, total: 0});
        }
        if (url.endsWith("/api/entities/person-1/context-card")) {
          return jsonResponse(contextCardFixture({entity: entityFixture({id: "person-1", display_name: "김민지"})}));
        }
        if (url.endsWith("/api/entity-facts") && init?.method === "POST") {
          return Promise.resolve({
            ok: false,
            status: 422,
            json: () =>
              Promise.resolve({
                error: {code: "validation_error", message: "Invalid fact_type.", details: {}},
              }),
          } as Response);
        }
        throw new Error(`Unexpected URL ${url}`);
      }),
    );

    render(<App />);

    await waitFor(() =>
      expect(screen.getByRole("heading", {level: 1, name: "김민지"})).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText("New structured fact type"), {
      target: {value: "unsupported_fact"},
    });
    fireEvent.change(screen.getByLabelText("New structured fact content"), {
      target: {value: "bad"},
    });
    fireEvent.click(screen.getByRole("button", {name: "Add structured fact"}));

    await waitFor(() =>
      expect(screen.getByText("validation_error: Invalid fact_type.")).toBeInTheDocument(),
    );
    expect(screen.getByRole("heading", {level: 1, name: "김민지"})).toBeInTheDocument();
  });

  it("renders candidate inbox filters, detail, actions, and edit-accept", async () => {
    window.history.pushState({}, "", "/candidates");
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.includes("/api/candidates?")) {
        const query = new URL(String(url)).searchParams;
        const filtered =
          query.get("candidate_type") === "observation" && query.get("sensitivity") === "high";
        return jsonResponse({
          items: [
            candidateFixture({
              id: filtered ? "candidate-filtered" : "candidate-1",
              sensitivity: filtered ? "high" : "medium",
            }),
          ],
          limit: 50,
          offset: 0,
          total: 1,
        });
      }
      if (String(url).match(/\/api\/candidates\/[^/]+\/accept$/)) {
        return jsonResponse(
          candidateFixture({
            status: "accepted",
            canonical_record_ref: "observations:obs-1",
          }),
        );
      }
      if (String(url).match(/\/api\/candidates\/[^/]+\/reject$/)) {
        return jsonResponse(candidateFixture({status: "rejected"}));
      }
      if (String(url).match(/\/api\/candidates\/[^/]+\/archive$/)) {
        return jsonResponse(candidateFixture({status: "archived"}));
      }
      if (String(url).match(/\/api\/candidates\/[^/]+\/needs-clarification$/)) {
        return jsonResponse(candidateFixture({status: "needs_clarification"}));
      }
      if (String(url).match(/\/api\/candidates\/[^/]+\/edit-accept$/)) {
        return jsonResponse(
          candidateFixture({
            status: "accepted",
            canonical_record_ref: "observations:obs-edited",
          }),
        );
      }
      throw new Error(`Unexpected URL ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    await waitFor(() => expect(screen.getAllByText("candidate-1").length).toBeGreaterThan(0));
    expect(screen.getAllByText(/후속 확인이 필요하다/).length).toBeGreaterThan(0);
    expect(screen.getByText("회의 말미에 다음 액션을 물었다.")).toBeInTheDocument();
    expect(fetchMock.mock.calls[0][0]).toContain("/api/candidates?status=pending&limit=50");

    fireEvent.change(screen.getByLabelText("Candidate type"), {target: {value: "observation"}});
    fireEvent.change(screen.getByLabelText("Sensitivity"), {target: {value: "high"}});
    await waitFor(() =>
      expect(screen.getAllByText("candidate-filtered").length).toBeGreaterThan(0),
    );
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("candidate_type=observation"))).toBe(
      true,
    );
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("sensitivity=high"))).toBe(
      true,
    );

    fireEvent.click(screen.getByRole("button", {name: "Accept"}));
    await waitFor(() => expect(screen.getByText("observations:obs-1")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", {name: "Reject"}));
    await waitFor(() => expect(screen.getAllByText("rejected").length).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole("button", {name: "Archive"}));
    await waitFor(() => expect(screen.getAllByText("archived").length).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole("button", {name: "Needs clarification"}));
    await waitFor(() =>
      expect(screen.getAllByText("needs_clarification").length).toBeGreaterThan(0),
    );

    fireEvent.change(screen.getByLabelText("Edited payload JSON"), {target: {value: "{"}});
    fireEvent.click(screen.getByRole("button", {name: "Edit accept"}));
    expect(screen.getByText("Invalid edited payload JSON.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Edited payload JSON"), {
      target: {
        value: JSON.stringify({
          subject_entity_id: "person-1",
          observation_type: "recent_interaction",
          content: "수정된 후속 확인",
          claim_type: "fact",
        }),
      },
    });
    fireEvent.click(screen.getByRole("button", {name: "Edit accept"}));
    await waitFor(() => expect(screen.getByText("observations:obs-edited")).toBeInTheDocument());
  });

  it("renders ego graph with filters and node and edge detail panels", async () => {
    window.history.pushState({}, "", "/graph");
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith("/api/entities?entity_type=person&limit=50")) {
        return jsonResponse({
          items: [
            entityFixture({id: "self-1", display_name: "Self", system_role: "self"}),
            entityFixture({id: "person-1", display_name: "김민지"}),
            entityFixture({id: "person-2", display_name: "박서연"}),
          ],
          limit: 50,
          offset: 0,
          total: 3,
        });
      }
      if (url.includes("/api/graph/ego/self-1")) {
        expect(url).toContain("depth=1");
        return jsonResponse({
          focal_entity_id: "self-1",
          depth: 1,
          nodes: [
            {
              entity_id: "self-1",
              display_name: "Self",
              entity_type: "person",
              status: "active",
              sensitivity: "medium",
              is_focal: true,
            },
            {
              entity_id: "person-1",
              display_name: "김민지",
              entity_type: "person",
              status: "active",
              sensitivity: "medium",
              is_focal: false,
            },
            {
              entity_id: "person-2",
              display_name: "박서연",
              entity_type: "person",
              status: "active",
              sensitivity: "high",
              is_focal: false,
            },
          ],
          edges: [
            {
              edge_id: "edge-1",
              from_entity_id: "self-1",
              to_entity_id: "person-1",
              relation_type: "friend",
              directed: false,
              status: "active",
              confidence: 0.9,
              sensitivity: "medium",
            },
            {
              edge_id: "edge-2",
              from_entity_id: "self-1",
              to_entity_id: "person-2",
              relation_type: "coworker",
              directed: true,
              status: "active",
              confidence: 0.8,
              sensitivity: "high",
            },
          ],
          filters_applied: {depth: 1},
        });
      }
      throw new Error(`Unexpected URL ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    await waitFor(() => expect(screen.getAllByText("김민지").length).toBeGreaterThan(0));
    expect(screen.getByText("박서연")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Relation type"), {target: {value: "friend"}});
    fireEvent.change(screen.getByLabelText("Sensitivity"), {target: {value: "medium"}});
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("relation_type=friend"))).toBe(
        true,
      ),
    );
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("sensitivity=medium"))).toBe(
      true,
    );

    fireEvent.click(screen.getByRole("button", {name: "Node 김민지"}));
    expect(screen.getByText("person-1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", {name: "Edge friend"}));
    expect(screen.getByText("edge-1")).toBeInTheDocument();
  });

  it("shows people filters and relationship context summaries", async () => {
    window.history.pushState({}, "", "/people");
    const fetchMock = vi.fn((url: string) => {
      if (url.includes("/api/entities?")) {
        return jsonResponse({
          items: [entityFixture({id: "person-1", display_name: "김민지"})],
          limit: 50,
          offset: 0,
          total: 1,
        });
      }
      if (url.endsWith("/api/entities/person-1/aliases")) {
        return jsonResponse({
          items: [
            {
              id: "alias-1",
              entity_id: "person-1",
              alias: "민지",
              normalized_alias: "민지",
              status: "active",
              confidence: 1,
              created_by: "user",
              created_at: "2026-06-10T00:00:00Z",
              updated_at: "2026-06-10T00:00:00Z",
            },
          ],
          limit: 200,
          offset: 0,
          total: 1,
        });
      }
      if (url.endsWith("/api/entities/person-1/context-card")) {
        return jsonResponse(
          contextCardFixture({
            entity: entityFixture({id: "person-1", display_name: "김민지"}),
            relationship_edges: [
              {
                id: "edge-1",
                from_entity_id: "self-1",
                to_entity_id: "person-1",
                relation_type: "friend",
                directed: false,
                claim_text: "친구",
                claim_type: "fact",
                properties: {},
                confidence: 1,
                status: "active",
                valid_from: null,
                valid_to: null,
                sensitivity: "medium",
                ai_use_policy: "cautious_use",
                created_by: "user",
                invalidated_by_edge_id: null,
                source_candidate_id: null,
                first_seen_at: null,
                last_seen_at: null,
                created_at: "2026-06-10T00:00:00Z",
                updated_at: "2026-06-10T00:00:00Z",
              },
            ],
            recent_context: [observationFixture({id: "obs-1"})],
          }),
        );
      }
      throw new Error(`Unexpected URL ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    await waitFor(() => expect(screen.getAllByText("김민지").length).toBeGreaterThan(0));
    expect(screen.getByText("민지")).toBeInTheDocument();
    expect(screen.getByText("1 relationships / 1 recent")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Status filter"), {target: {value: "active"}});
    fireEvent.change(screen.getByLabelText("Sensitivity filter"), {target: {value: "medium"}});
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("status=active"))).toBe(
        true,
      ),
    );
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("sensitivity=medium"))).toBe(
      true,
    );
  });

  it("keeps people visible when row context summaries fail", async () => {
    window.history.pushState({}, "", "/people");
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url.includes("/api/entities?")) {
          return jsonResponse({
            items: [entityFixture({id: "person-1", display_name: "김민지"})],
            limit: 50,
            offset: 0,
            total: 1,
          });
        }
        if (
          url.endsWith("/api/entities/person-1/aliases") ||
          url.endsWith("/api/entities/person-1/context-card")
        ) {
          return Promise.reject(new TypeError("Failed to fetch"));
        }
        throw new Error(`Unexpected URL ${url}`);
      }),
    );

    render(<App />);

    await waitFor(() => expect(screen.getAllByText("김민지").length).toBeGreaterThan(0));
    expect(screen.getByText("Context unavailable")).toBeInTheDocument();
    expect(screen.queryByText("Failed to fetch")).not.toBeInTheDocument();
  });
});

function entityFixture(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "person-1",
    entity_type: "person",
    display_name: "김민지",
    canonical_name: "김민지",
    properties: {},
    confirmation_status: "confirmed",
    status: "active",
    sensitivity: "medium",
    ai_use_policy: "cautious_use",
    created_by: "user",
    system_role: null,
    is_system: false,
    first_seen_at: null,
    last_referenced_at: null,
    created_at: "2026-06-10T00:00:00Z",
    updated_at: "2026-06-10T00:00:00Z",
    ...overrides,
  };
}

function observationFixture(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "obs-1",
    subject_entity_id: "person-1",
    related_entities: [],
    observation_type: "recent_interaction",
    content: "Observation",
    claim_type: "fact",
    confidence: 1,
    sensitivity: "medium",
    ai_use_policy: "cautious_use",
    status: "active",
    valid_from: null,
    valid_to: null,
    occurred_at: null,
    recency_weight: null,
    created_by: "user",
    source_candidate_id: null,
    embedding: null,
    embedding_status: "pending",
    embedding_error: null,
    embedding_model: null,
    embedding_dim: null,
    embedding_created_at: null,
    created_at: "2026-06-10T00:00:00Z",
    updated_at: "2026-06-10T00:00:00Z",
    ...overrides,
  };
}

function contextCardFixture(overrides: Partial<Record<string, unknown>> = {}) {
  const entity = entityFixture();
  return {
    entity,
    aliases: [],
    profile_facts: [],
    relationship_edges: [],
    stable_context: [],
    recent_context: [],
    communication_context: [],
    cautions: [],
    provenance_summary: {
      fact_count: 0,
      edge_count: 0,
      observation_count: 0,
      evidence_count: 0,
      evidence: [],
    },
    retrieval_hints: {
      entity_id: entity.id,
      canonical_name: entity.canonical_name,
      aliases: [],
      entity_type: "person",
    },
    ...overrides,
  };
}

function candidateFixture(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "candidate-1",
    candidate_type: "observation",
    target_entity_id: "person-1",
    payload: {
      subject_entity_id: "person-1",
      observation_type: "recent_interaction",
      content: "후속 확인이 필요하다.",
      claim_type: "fact",
    },
    evidence: [
      {
        id: "evidence-1",
        candidate_id: "candidate-1",
        episode_id: "episode-1",
        excerpt: "회의 말미에 다음 액션을 물었다.",
        confidence: 0.8,
        created_at: "2026-06-10T00:00:00Z",
      },
    ],
    confidence: 0.8,
    sensitivity: "medium",
    suggested_action: "accept",
    status: "pending",
    created_by: "agent",
    created_at: "2026-06-10T00:00:00Z",
    updated_at: "2026-06-10T00:00:00Z",
    resolved_at: null,
    resolved_by: null,
    resolution_note: null,
    canonical_record_ref: null,
    supersedes_candidate_id: null,
    supersedes_record_ref: null,
    ...overrides,
  };
}
